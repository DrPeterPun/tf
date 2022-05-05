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
MIN_HB = MAX_TIME_DIF/3*0.00000001
MAX_HB = MAX_TIME_DIF/2*0.00000001


#//////////////////
#degub stuff
start_time= time.time_ns()
def buildString(n):
    s = ""
    for a in n:
        s+= str(a) + "\n"
    logging.info(s)
    #raise Exception(s)

def printState():
    buildString(["node id:",node_id,"leader", leader_id,"kvsotr",kvstore,"cur term", current_term, "log ",log, "commit indez e last applied",commitIndex,lastApplied,"candidate, votes, voted for",candidate,votes,votedFor,"timeout dict", timeout_dict,"curr time", time.time_ns()])
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
def check_timestamp(node):
    if timeout_dict.get(node,None) != None:
        return cur_time-timeout_dict[node]<MAX_TIME_DIF

#updates a node's timestamp
def add_timestamp(node):
    timeout_dict[node]=time.time_ns()

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
    buildString(["HBdest",dest,"nextIndex",nextIndex,"log",log])
    prevIndex = nextIndex[dest]-1
    prevTerm=log[nextIndex[dest]-1][1]
    send(node_id, dest, type='AppendEntries', term=current_term, prevIndex = prevIndex,prevTerm=prevTerm ,entries=[],commit=commitIndex)

#while leader, pereodicly sends heartbeats to a node. Period between heartbeats is variable as to not cause network congestion
def recursive_heartbeats(dests):
    if is_leader():
        buildString(["sending HB"])
        #divido por 5 pq tem de se mandar hbs suficiente para nao dar timeout, senao ta sempre a haver eleicoes
        sec = random.uniform(MIN_HB,MAX_HB)/5
        #remover o lider para nao ser self msg
        dests= list(filter(lambda elem: elem!=leader_id, node_ids))
        for dest in dests:
            heartbeat(dest)
        Timer(sec, recursive_heartbeats,[dests]).start()

#periodicly checks if the leadder is alive. if its not starts a vote for new leader
def leader_alive_checker():
    # if not is_leader() and leader not alive and not in election:
        if not is_leader() and not check_timestamp(leader_id) and not in_election:
            buildString(["lead is dead"])
            start_election()
            sec = random.uniform(MIN_HB,MAX_HB)
            Timer(0.5, leader_alive_checker)
        else:
            buildString(["leader alive, resuming timeout checker"])
            #sec = random.uniform(MIN_HB,MAX_HB)
            #buildString([timeout_dict.items(),MIN_HB,MAX_HB,sec,time.time_ns()])
            # como o lider ja faz hb com intervalos random este check nao precisa de ser com intervalos random
            Timer(0.5, leader_alive_checker)
            #Timer(sec, buildString,[timeout_dict.items()]).start()

#cases: election ended and this node won, this node won, election still ongoing
#node won : nothing to do, end recurtion; should be handeled when receiving the fisrt hb from new leadder
#node lost: nothing to do, end recurtion; should be handeled when receiving the fisrt hb from new leadder
#ongoing: new vote

def election_checker():
    #state of a follower
    global votedFor, votes, candidate
    #eleicao ainda nao acabou acabou, entao deu timeout e comecamos uma nova, mas este nodo fica candidado
    if in_election:

        buildString(["election timeout, starting new election"])
        start_election()
    #eleicao acabou, comecamos a verificar otura vez se o lider deu timeout
    else:    
        buildString(["election ended"])
        Timer(0.5, leader_alive_checker).start()

#starts a new vote
def start_election():
    global current_term
    current_term += 1
    sec = random.uniform(MIN_HB,MAX_HB)
    buildString(["starting new elections, new term", current_term,"sec, min max hb",sec,MIN_HB,MAX_HB])
    request_vote()
    #after sec seconds checks if the thelection ended.
    Timer(0.25, election_checker).start()

#starts a new vote and sets itself as candidate
def request_vote():
    global current_term, votes, votedFor, in_election, candidate
    buildString(["Requesting new Vote"])
    votes=0
    in_election = True
    votedFor=None
    candidate=True
    for dest in node_ids:
        lastLogIndex=len(log)-1
        lastLogTerm=log[-1][1]
        send(node_id, dest, type='RequestVote', term=current_term,prevLogIndex = lastLogIndex ,lastLogTerm=lastLogTerm, candidateId=node_id)

# edits variables as to not in an election anymore.
def end_vote():
    global in_election,candidate,votes,votedFor
    buildString(["vote ended, new leader is",leader_id])
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
    buildString(["became leader","log",log,"match index",matchIndex])
    end_vote()
    recursive_heartbeats(node_ids)

def restore_kv_state():
    for i in range(1,commitIndex):
        commit_command(log[i])

def commit_command(command):
    buildString(["commiting command", command])
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
    elif msg.body.type == 'AppendEntries':
        add_timestamp(msg.src)
        #raise Exception(log[msg.body.prevIndex])
        #buildString([ msg.body.prevIndex,log,log[msg.body.prevIndex]])    
        #there is a new leader, convert current node to follower
        if msg.body.term>current_term:
            end_vote()
            nextIndex=None
            matchIndex=None
            unanswered = None
            leader_id=msg.src
            buildString(["there is a new leader"])
            printState()
            current_term=msg.body.term
        #term receives less than current term
        elif msg.body.term<current_term:
            reply(msg,type='AppendEntriesRes',res=False,term=current_term)
            buildString(["msg term",msg.body.term,"current term", current_term, "log",log, "msg entries" ,msg.body.entries  ])
            return
        # terms not matching in last log entry not sent
        a=[]
        try:
            a = log[msg.body.prevIndex]
            if a[1]!=msg.body.prevTerm:
            #elif log[msg.body.prevIndex][1]!=msg.body.prevTerm:
                reply(msg,type='AppendEntriesRes',res=False,term=current_term)
                return
        except:
            buildString([ "280",log,msg.body.prevIndex,commitIndex,node_id,msg.body.entries])
            return
        
        #check if any existing entries have diferent terms than the received ones
        newstart=0
        if len(msg.body.entries)>0:
            for i in range(1,len(msg.body.entries)):
                buildString([ "355", log,msg.body.entries ,msg.body.prevIndex ,commitIndex ,node_id,i ])
                #check is there is an entry on that log index
                entry = None
                if len(log)>msg.body.prevIndex+i:
                    entry=log[msg.body.prevIndex+i]
                #if the indexes dont match
                if entry!=None and entry[1]!=msg.body.entries[i-1][1]:
                    #delete everything in front
                    log = log[:msg.body.prevIndex+i-1]
                    newstart=i-1
                    commitIndex = len(log)-1
                    lastApplied = len(log)-1
                    #redoo all the operations!! from the begining
                    restore_kv_state()
                    break

        dif = msg.body.prevIndex-len(log)
        #para cada elemento das entries a pardir do "fim" do log, dar append e fazer a opecarao
        for entry in msg.body.entries[newstart:]:
            #buildString([ "313",log,msg.body.prevIndex,commitIndex,node_id,entry])
            log.append(entry)
            commit_command(entry)
        #for i in range(len(msg.body.entries[dif:])-1):
        #    command=msg.body.entries[dif+i]
        #    buildString([ "308",log,msg.body.prevIndex,commitIndex,node_id,entry])
        #    log.append(command)
        #    commit_command(command)

        # if leadercommit > commitIndex set commitIndex = min(leadercommit , index of last new entry)
        #log[-1][1] quase a certeza  que isto esta mal, mas nao estou abem a ver oqq devia ser, to be fixed in the future
        if msg.body.commit>commitIndex:
            #commitIndex=min(msg.body.commit, log[-1][1])
            buildString([ "379",log,msg.body.prevIndex,commitIndex,node_id])
            commitIndex=min(msg.body.commit, len(log))
            restore_kv_state()

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

        #nao estamos updated o suficiente para o term desse nodo
        if msg.body.term > current_term:
            return

        elif (msg.body.res):
            #update next index and match index
            nextIndex[msg.src] = msg.body.next
            matchIndex[msg.src] = msg.body.commit

        #k 
        else:
            nextIndex[msg.src] -=1
            dest = msg.src
            buildString(["387##########:","node",node_id,"current term" ,current_term,"next I" , nextIndex,"log",log,"dest", dest])
            send(node_id, dest, type='AppendEntries', term=current_term, prevIndex = nextIndex[dest]-1,prevTerm=log[nextIndex[dest]-1][1] ,entries=log[nextIndex[dest]:] if len(log)>nextIndex[dest] else [] ,commit=commitIndex)
       
        # verifica se ja ha um consenso de replies
        #buildString([ "2",log,unanswered,commitIndex])    
        flag = True
        maxn = commitIndex
        majority = len(node_ids)//2+1
        #poe em maxn o N maximo tal que existe um consenso de que commitIndex=N
        #aka da commit a tods os comands para os quais existe um consenso.

        while(flag and msg.body.res):
            #se ha consenso deste commit, da tbm o lider o commit
            if count_commit_index_consensus(maxn+1)>=majority:
                buildString([ "dei commit ao commando ",log[maxn], log, unanswered,commitIndex,matchIndex,majority,count_commit_index_consensus(maxn+1)])    
                maxn+=1
                buildString([ "3",log,unanswered,commitIndex])    
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
            buildString(["Bad election request, term is not up to date", votedFor, "at time", time.time_ns()])
        elif (node_id==msg.src):
            #current_term=msg.body.term
            votedFor=node_id
            buildString(["voting for myself", votedFor, "at time", time.time_ns(),"nr votes", votes])
            reply(msg,type='RequestVoteRes',term=current_term,res=True)
        else:
            #if didnt vote yet, or voted in the request src, and the logs are congruent vote in the src
            buildString(["log atual",log,"prevlog index",msg.body.prevLogIndex, " last log term", msg.body.lastLogTerm])
            if ( votedFor == None or votedFor==msg.src ) and msg.body.prevLogIndex>=len(log)-1 and msg.body.lastLogTerm >= log[-1][1]:
                #current_term=msg.body.term
                in_election=True
                votedFor = msg.src
                #current_term=msg.body.term
                reply(msg,type='RequestVoteRes',term=current_term,res=True)
                buildString(["election started and voted vor", votedFor, "at time", time.time_ns()])
                #start election timout timer (0.1sec)
                Timer(0.25, election_checker).start()
            else:
                reply(msg,type='RequestVoteRes', term=current_term, res= False)

    elif msg.body.type == 'RequestVoteRes':
        add_timestamp(msg.src)

        buildString(["Got a response to the vote Request #475"])
        printState()
        buildString(["resposta",msg.body.res,"majority", len(node_ids)//2+1])
        if not in_election:
            #ignorar se nao tiver numa eleicao
            return
        
        if not candidate:
            #ignorar se nao for candidato
            return

        if msg.body.res:
            buildString(["antes do incremento no voto #487",votes])
            votes+=1
            buildString(["depois  #489",votes])
        
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