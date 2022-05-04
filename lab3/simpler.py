#!/usr/bin/env python

# 'echo' workload in Python for Maelstrom
# with an addtional custom MyMsg message

import logging
from concurrent.futures import ThreadPoolExecutor
from ms import send, receiveAll, reply, exitOnError
from threading import Timer
import time
import random

logging.getLogger().setLevel(logging.DEBUG)
executor=ThreadPoolExecutor(max_workers=1)
leader_id = None
node_id=None
node_ids=[]


# key value store (key: value)
kvstore = {}
#nr do mandato
current_term = 0
#lista de pares (pedido, current term)
log = []
log.append( ( ( 'pass',None) ,current_term) )
#em que lider votou, (candidateId)
votedFor = None
# indice da maior entrada que foi commited
commitIndex = 0
# indice da maior entrada aplicada
lastApplied = 0
# bool se é ou nao candidato
candidate = False
#nr of votes received
votes = None
#var que diz se existe uma eleicao
in_election = False
#timeout dict,guarda: (node_id : timestamp)
timeout_dict= {}

#LEADER ONLY
#indice da proxima entrada a ser ENVIADA a cada servidor (init a laslogindex+1)
nextIndex = None
#indice da entrada com indice maior REPLICADA em casa servidor (init a 0)
matchIndex = None
#dict de log_index: msg; tem todas as msgs que ainda nao foram respondidas
unanswered = None
#tempo maximo sem resposta de um nodo para o considerar ofline 0.1s || in ns
# hb time varia entre 0.2 e 0.5 ||in sec
#MAX_TIME_DIF = 100_000
MAX_TIME_DIF = 100_000_000
MIN_HB = MAX_TIME_DIF/5*0.00000001
MAX_HB = MAX_TIME_DIF/2*0.00000001


#//////////////////
#degub stuff
def buildString(n):
    s = ""
    for a in n:
        s+= str(a) + "\n"
    logging.warning(s)
    #raise Exception(s)

#//////////////////

#list of active nodes
def active_nodes():
    return list(filter(lambda elem: check_timestamp(elem), node_ids))

#checks if current node is the leader, returns True if it IS the leadder
#not the leader -> reply with error code 11 and return false
def is_leader(msg=None):
    if(node_id != leader_id):
        if (msg!=None):
            reply(msg, type="error",code=11,text='Not Leader' )
        return False
    return True

#conta o nr de nodos com commit index maior ou igual do que n; aka ja deram commit a entrada com indice n
#WRONG! 
def count_commit_index_consensus(n):
    global matchIndex
    count = 0
    for i in matchIndex.values():
        if i>=n:
            count +=1
    return count

#timestamp_dict , node_id
#check if a node is alive
#returns true if node is alive
def check_timestamp(node_id):
    ######################################debug
    if node_id=='n1':
        return False
    if timeout_dict.get(node_id,None) != None:
        return time.time_ns()-timeout_dict[node_id]<MAX_TIME_DIF

#updates a node's timestamp
def add_timestamp(node_id):
    timeout_dict[node_id]=time.time_ns()

#starts all timestamps to current time
def init_timestamps(node_ids):
    global timeout_dict
    t = time.time_ns()
    for id in node_ids:
        timeout_dict[id]=t

#sends a heartbeat to a node
def heartbeat(dest):
    global nextIndex, log, commitIndex
    #send(node_id, dest, type='AppendEntries', term=current_term,prevLogIndex = nextIndex[dest]-1 ,entries=[],commit=commitIndex)
    prevIndex = nextIndex[dest]-1
    prevTerm=log[nextIndex[dest]-1][1]
    send(node_id, dest, type='AppendEntries', term=current_term, prevIndex = prevIndex,prevTerm=prevTerm ,entries=log,commit=commitIndex)

#while leader, pereodicly sends heartbeats to a node. Period between heartbeats is variable as to not cause network congestion
def recursive_heartbeats(dests,min_time,max_time):
    if is_leader():
        sec = random.uniform(min_time,max_time)
        #remover o lider para nao ser self msg
        dests= list(filter(lambda elem: elem!=leader_id, node_ids))
        for dest in dests:
            heartbeat(dest)
        Timer(sec, recursive_heartbeats,[dests,min_time,max_time]).start()

#periodicly checks if the leadder is alive. if its not starts a vote for new leader
def leader_alive_checker():
    # if not is_leader() and leader not alive  and not in election:
        if not is_leader() and not check_timestamp(leader_id) and not in_election:
            start_election()
            #sec = random.uniform(MIN_HB,MAX_HB)
            #Timer(sec, leader_alive_checker).start()
        else:
            #sec = random.uniform(MIN_HB,MAX_HB)
            #buildString([timeout_dict.items(),MIN_HB,MAX_HB,sec,time.time_ns()])
            # como o lider ja faz hb com intervalos random este check nao precisa de ser com intervalos random
            Timer(0.1, leader_alive_checker).start()
            #Timer(sec, buildString,[timeout_dict.items()]).start()

#cases: election ended and this node won, this node won, election still ongoing
#node won : nothing to do, end recurtion; should be handeled when receiving the fisrt hb from new leadder
#node lost: nothing to do, end recurtion; should be handeled when receiving the fisrt hb from new leadder
#ongoing: new vote

def election_checker(min_time,max_time):
    #state of a follower
    global votedFor, votes, candidate
    #eleicao ainda nao acabou acabou, entao deu timeout e comecamos uma nova
    if in_election:
        start_election()
    #eleicao acabou, comecamos a verificar otura vez se o lider deu timeout
    else:    
        Timer(0.1, leader_alive_checker).start()

#starts a new vote
def start_election():
    global current_term,in_election
    current_term += 1
    in_election=True
    request_vote()
    sec = random.uniform(MIN_HB,MAX_HB)
    #after sec seconds checks if the thelection ended.
    Timer(sec, election_checker).start()

#starts a new vote and sets itself as candidate
def request_vote():
    global current_term, votes, votedFor, candidate
    votes=0
    votedFor=None
    candidate=True
    lastLogIndex=len(log)-1
    lastLogTerm=log[-1][1]
    for dest in node_ids:
        send(node_id, dest, type='RequestVote', term=current_term,prevLogIndex = lastLogIndex ,lastLogTerm=lastLogTerm, candidateId=node_id)

# edits variables as to not in an election anymore.
def end_vote():
    global in_election,candidate,votes,votedFor
    in_election=False
    candidate=False
    votes=None
    votedFor=None

def become_leader():
    global matchIndex, nextIndex, unanswered, leader_id, node_ids, log
    nextIndex = {id :len(log) for id in node_ids}
    matchIndex = {id:0 for id in node_ids}
    unanswered = {}
    leader_id = node_id
    end_vote()
    recursive_heartbeats(node_ids,MIN_HB,MAX_HB)

def restore_kv_state():
    global commitIndex, lastApplied
    for i in range(1,commitIndex):
        commit_command(log[i])
    

def commit_command(command):
    if command[0]=='write':
        kvstore[command[1][0]]=command[1][1]
        return None
    elif command[0]=='cas':
        frm = command[1][1][0]
        to = command[1][1][1]
        key = command[1][0]
        if kvstore.get(key,None)==None:
            return 20
        elif kvstore[key]==frm:
            kvstore[key]=to
            return None
        else:
            return 22
    elif command[0]=='pass':
        return None

def handle(msg):
    # State
    global node_id, node_ids, current_term, kv_store, log, votedFor, commitIndex, lastApplied, candidate, votes, timeout_dict, leader_id, nextIndex, matchIndex ,unanswered, in_election

    # Message handlers
    if msg.body.type == 'init':
        node_id = msg.body.node_id
        node_ids = msg.body.node_ids
        leader_id = node_ids[0]
        logging.info('node %s initialized', node_id)
        reply(msg, type='init_ok')
        init_timestamps(node_ids)
        if (not is_leader()):
            leader_alive_checker()
            return

        #becoming leader
        #send hb to everyone, 
        become_leader()

    #leader
    #key, value; key and value to insert
    elif msg.body.type == 'write':
        # se nao for o leader devolver erro 
        if (not is_leader(msg)):
            return

        key = msg.body.key
        value = msg.body.value
        
        log.append( ( ('write' ,(key,value) ),current_term) )
        lastLogIndex = len(log)-1
        unanswered[lastLogIndex] = msg
        for dest in node_ids:
            if dest != node_id and lastLogIndex>= nextIndex[dest]:
                send(node_id, dest, type='AppendEntries', term=current_term,entries=log[nextIndex[dest]:], prevIndex = nextIndex[dest]-1,prevTerm=log[nextIndex[dest]-1][1] ,commit=commitIndex)
    
    #leader
    #key, value; key and value to insert
    elif msg.body.type == 'cas':
        # se nao for o leader devolver erro 
        if (not is_leader(msg)):
            return

        key = msg.body.key
        frm = getattr(msg.body, 'from')
        to = msg.body.to
        
        log.append( ( ('cas' ,(key,(frm,to))) ,current_term ) )
        lastLogIndex = len(log)-1
        unanswered[lastLogIndex] = msg
        for dest in node_ids:
            if dest != node_id and lastLogIndex>= nextIndex[dest]:
                send(node_id, dest, type='AppendEntries', term=current_term, entries=log[nextIndex[dest]:],prevIndex = nextIndex[dest]-1,prevTerm=log[nextIndex[dest]-1][1] ,commit=commitIndex)

    #leader
    #since the leader is setting the log anyway, this can be answered to right away
    elif msg.body.type == 'read' :
        # se nao for o leader devolver erro 
        if (not is_leader(msg)):
            return
        if kvstore.get(msg.body.key,None) != None:
            reply(msg,type='read_ok', value=kvstore[msg.body.key])
        else:
            reply(msg, type='error', code=20, text='Invalid Key')

    #follower
    #entries; list og logs to commit to local log
    #term; termo do lider
    #prevLogIndex; indice do Log imediatamente antes ao primeiro enviado
    #prevLogTerm; termo da primeira entrada do prevLogIndex
    #commit; commitIndex do lider
    #################################################WRONG######################################
    elif msg.body.type == 'AppendEntries':
        add_timestamp(msg.src)
        buildString([ msg.body.prevIndex,log,log[msg.body.prevIndex]])    

        #term receives less than current term
        if msg.body.term<current_term:
            reply(msg,type='AppendEntriesRes',res=False,term=current_term)
            return
        a=[]
        try:
            a = log[msg.body.prevIndex]
        except:
            buildString([ "311",log,msg.body.prevIndex,commitIndex,node_id,msg.body.entries])    
            pass
        # terms not matching in last log entry not sent

        #there is a new leader, convert current node to follower
        if msg.body.term>current_term:
            end_vote()
            nextIndex = None
            matchIndex = None
            unanswered = None
            leader_id = msg.src
            current_term = msg.body.term


        ##################### degub
        #reply(msg,type='AppendEntriesRes',res=True,term=current_term,next=len(log),commit=commitIndex)
        #return 
        #####################

        #check if any existing entries have diferent terms than the received ones

                # if leadercommit > commitIndex set commitIndex = min(leadercommit , index of last new entry)
        if msg.body.commit>commitIndex:
            #commitIndex=min(msg.body.commit, log[-1][1])
            buildString([ "326",log,msg.body.prevIndex,commitIndex,node_id])
            commitIndex=min(msg.body.commit, len(log))
            restore_kv_state()
            reply(msg,type='AppendEntriesRes',res=True,term=current_term,next=len(log),commit=commitIndex)
            return 
            
        log = msg.body.entries
        lastApplied = len(log)-1
        restore_kv_state()
        commitIndex = len(log)-1

        reply(msg,type='AppendEntriesRes',res=True,term=current_term,next=len(log),commit=commitIndex)

    #leader
    #(bool) res; description if write was sucessfull or not
    #(int) next; tamanho do log enviado para o cliente
    elif msg.body.type == 'AppendEntriesRes':
        add_timestamp(msg.src)
        if not is_leader(msg):
            #talvez retornar um codigo de erro aqui
            # a is_leader retorna o proprio codigo de erro
            #buildString([ "1",log,unanswered,commitIndex]) 
                
            return

        if (msg.body.res):
            #update next index and match index
            nextIndex[msg.src] = msg.body.next
            matchIndex[msg.src] = msg.body.commit
            
        else:
            nextIndex[msg.src] -=1
            dest = msg.src
            send(node_id, dest, type='AppendEntries', term=current_term, prevIndex = nextIndex[dest]-1,prevTerm=log[nextIndex[dest]-1][1] ,entries=log[nextIndex[dest]:],commit=commitIndex)
       
        # verifica se ja ha um consenso de replies
        #buildString([ "2",log,unanswered,commitIndex])    
        flag = True
        maxn = commitIndex
        majority = len(node_ids)//2+1
        #poe em maxn o N maximo tal que existe um consenso de que commitIndex=N
        #aka da commit a tods os comands para os quais existe um consenso.

        #nao faz sentido ver se mudaram cenas se o que recebeu um falso
        while(flag and msg.body.res):
            #buildString([ "3",log,unanswered,commitIndex,matchIndex,majority,count_commit_index_consensus(maxn+1)])    
            #se ha consenso deste commit, da tbm o lider o commit
            if count_commit_index_consensus(maxn+1)>=majority:
                buildString([ "380",log,unanswered,commitIndex,matchIndex,majority,count_commit_index_consensus(maxn+1)])    
                maxn+=1
                # aplies the command, changing the local kv_store to reflect the new operation
                error_code = commit_command(log[maxn])
                #reply with wth is the correct reply
                rmsg = unanswered.pop(maxn)
                command=log[maxn]
                if command[0]=='write':
                    reply(rmsg, type='write_ok')
                elif command[0]=='cas':
                    if error_code!=None:
                        reply(rmsg,type='cas_ok')
                    else:
                        error_text = 'Invalid Key' if code == 20 else 'Invalid From'
                        reply(rmsg,code=error_code, text=error_text)
                else:
                    #algo corrreu mal
                    pass
            else:
                flag=False
        commitIndex = maxn

    #candidate
    #term
    #candidateId
    #lastLogIndex
    #lasLogTerm
    elif msg.body.type == 'RequestVote':
        add_timestamp(msg.src)
        if msg.body.term<current_term:
            reply(msg,type='RequestVoteRes', term=current_term, res= False)
        else:
            #if didnt voe yet, or voted in the request src, and the logs are congruent vote in the src
            if ( votedFor == None or votedFor==msg.src ) and msg.body.prevLogIndex>=len(log)-1 and msg.body.lastLogTerm >= log[-1][1]:
                in_election=True
                votedFor = msg.src
                current_term=msg.body.term
                reply(msg,type='RequestVoteRes',term=current_term,res=True)
            else:
                #buildString([log,msg.body.prevLogIndex,msg.body.lastLogTerm,votedFor,node_id])
                reply(msg,type='RequestVoteRes', term=current_term, res= False)

    elif msg.body.type == 'RequestVoteRes':
        add_timestamp(msg.src)

        if not in_election:
            #ignorar se nao tiver numa eleicao
            return

        if msg.body.res:
            votes+=1
        majority = len(node_ids)//2+1
        if votes>=majority:
            #become leader
            become_leader()

    else:
        logging.warning('unknown message type %s', msg.body.type)

# Main loop
executor.map(lambda msg: exitOnError(handle, msg), receiveAll())

# schedule deferred work with:
# executor.submit(exitOnError, myTask, args...)

# schedule a timeout with:
# from threading import Timer
# Timer(seconds, lambda: executor.submit(exitOnError, myTimeout, args...)).start()

# exitOnError is always optional, but useful for debugging