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

# key value store (key: value)
kvstore = {}
#nr do mandato
current_term = 0
#lista de pares (pedido, current term)
log = []
log.append( ('pass',current_term) )
currentIndex = 1
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
#timeout dict,guarda: (node_id : timestamp)
timeout_dict= {}

#LEADER ONLY
#indice da proxima entrada a ser ENVIADA a cada servidor (init a laslogindex+1)
nextIndex = None
#indice da entrada com indice maior REPLICADA em casa servidor (init a 0)
matchIndex = None
#tempo maximo sem resposta de um nodo para o considerar ofline 0.1s
MAX_TIME_DIF = 100_000_000
MIN_HB = MAX_TIME_DIF/5
MAX_HB = MAX_TIME_DIF/2

#//////////////////
#degub stuff
def megaprint(s):
    print("//////////////////////////////////")
    print("//////////////////////////////////")
    print(s) 
    print("//////////////////////////////////")
    print("//////////////////////////////////")

#degub stuff
#//////////////////

#list of active nodes
def active_nodes():
    return list(filter(lambda elem: check_timestamp(elem), node_ids))

#checks if current node is the leader, returns True if it IS the leadder
#not the leader -> reply with error code 11 and return false
def is_leader(msg=None):
    if(node_id != leader_id):
        if (msg!=None):
            reply(msg, type="error",code=11 )
        return False
    return True

#conta o nr de nodos com commit index maior do que n
#WRONG! 
def count_commit_index_consensus(n,log):
    count = 0
    for i in matchIndex:
        if i>n:
            count +=1
    return count

#timestamp_dict , node_id
#check if a node is alive
def check_timestamp(node_id):
    if timeout_dict.get(node_id) != None:
        megaprint(timeout_dict)     
        return timeout_dict[node_id]-time.time_ns()<MAX_TIME_DIF

#updates a node's timestamp
def add_timestamp(node_id):
    timeout_dict[node_id]=time.time_ns()

#starts all timestamps to current time
def init_timestamps(node_ids):
    t = time.time_ns()
    for id in node_ids:
        timeout_dict[id]=t

#sends a heartbeat to a node
def heartbeat(dest):
    send(node_id, dest, type='AppendEntries', term=current_term,prevLogIndex = nextIndex[dest]-1 ,entries=[],commit=commitIndex)

#while leader, pereodicly sends heartbeats to a node. Period between heartbeats is variable as to not cause network congestion
def recursive_heartbeats(dest,min_time,max_time):
    if is_leader():
        heartbeat(dest)
        sec = random.randrange(min_time,max_time)
        Timer(sec, lambda: executor.submit(reccursive_heartbeats,min_time,max_time))

#periodicly checks if the leadder is alive. if its not starts a vote for new leader
def leader_alive_checker():
    # if not is_leader():
        if not check_timestamp(leader_id):
            start_vote()
        else:
            sec = random.randrange(min_time,max_time)
            Timer(sec, lambda: executor.submit(leader_alive_checker,min_time,max_time))

#cases: election ended and this node won, this node won, election still ongoing
#node won : nothing to do, end recurtion; should be handeled when receiving the fisrt hb from new leadder
#node lost: nothing to do, end recurtion; should be handeled when receiving the fisrt hb from new leadder
#ongoing: new vote

def election_checker(min_time,max_time):
    #state of a follower
    if votedFor==None and votes==None and candidate==False:
        start_vote()

#starts a new vote
def start_vote():
    global current_term 
    current_term += 1
    request_vote()
    #provisional values
    min_time = MIN_HB
    max_time = MAX_HB
    sec = random.randrange(min_time,max_time)
    Timer(sec, lambda: executor.submit(election_checker))

#starts a new vote and sets itself as candidate
def request_vote():
    global candidate
    candidate = True 
    for dest in node_ids:
        lastLogIndex=len(log[-1])
        lastLogTerm=log[-1][1]
        send(node_id, dest, type='RequestVote', term=current_term,prevLogIndex = lastLogIndex ,lastLogTerm=lastLogTerm, candidateId=node_id)

# edits variables as to not be a candidate anymore
def end_vote():
    candidate=False
    votes=None
    votedFor=None

def become_leader():
    pass

def restore_kv_state():
    for i in range(1,commitIndex):
        commit_command(log[i])

def commit_command(command):
    if command[0]=='write':
        kvstore[command[1][0]]=command[1][1]
    elif command[0]=='cas':
        frm = command[1][1][0]
        to = command[1][1][1]
        key = command[1][0]
        if kvstore[key]==frm:
            kvstore[key]=to
    elif command[0]=='pass':
        pass



def handle(msg):
    # State
    global node_id, node_ids, current_term, kv_store, log, currentIndex, votedFor, commitIndex, lastApplied, candidate, votes, timeout_dict

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

        for node in node_ids:
            if not is_leader():
                recursive_heartbeats(node,MIN_HB,MAX_HB)
        nextIndex = [len(log) for _ in range(len(node_ids))]
        matchIndex = [0 for _ in range(len(node_ids)) ]

    #leader
    #key, value; key and value to insert
    elif msg.body.type == 'write':
        # se nao for o leader devolver erro 
        if (not is_leader(msg)):
            return

        key = key.body.key
        value = msg.body.value
        
        log.append( ( 'write' ,(key,value) ,current_term) )
        lastLogIndex = len(log)
        for dest in node_ids:
            if dest != node_id and lastLogindex>= nextIndex[dest]:
                send(node_id, dest, type='AppendEntries', term=current_term,prevLogIndex = nextIndex[dest]-1 ,entries=log[nextIndex[dest]:],commit=commitIndex)
    
    #leader
    #key, value; key and value to insert
    elif msg.body.type == 'cas':
        # se nao for o leader devolver erro 
        if (not is_leader(msg)):
            return

        key = key.body.key
        frm = getattr(msg.body, 'from')
        to = msg.body.to
        
        log.append( ( 'cas' ,(key,(frm,to)) ,current_term) )
        lastLogIndex = len(log)
        for dest in node_ids:
            if dest != node_id and lastLogindex>= nextIndex[dest]:
                send(node_id, dest, type='AppendEntries', term=current_term,prevLogIndex = nextIndex[dest]-1 ,entries=log[nextIndex[dest]:],commit=commitIndex)

    #leader
    #since the leader is setting the log anyway, this can be responded right away
    elif msg.body.type == 'read' :
        # se nao for o leader devolver erro 
        if (not is_leader(msg)):
            return

        reply(msg,type='read_ok', value=kvstore[msg.body.key])

    #follower
    #entries; list og logs to commit to local log
    #term; termo do lider
    #prevLogIndex; indice do Log imediatamente antes ao primeiro enviado
    #prevLogTerm; termo da primeira entrada do prevLogIndex
    #commit; commitIndex do lidera
    #not present yet //////////// leaderID, Se receberes uma msg com um leader id diferente alteras o leader id para ser esse? ( caso o term seja maior do que o que tens atualmente)
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    elif msg.body.type == 'AppendEntries':
        add_timestamp(msg.body.src)
        #term receives less than current term
        if msg.body.term<current_term:
            reply(msg,type='AppendEntriesRes',res=False,term=current_term)
            return
        # terms not matching
        elif log[msg.body.prevLogIndex][1]!=msg.body.entries[0][1]:
            reply(msg,type='AppendEntriesRes',res=False,term=current_term)
            return

        #there is a new leader, convert current node to follower
        elif msg.body.term>current_term:
            end_vote()
            nextIndex=None
            matchIndex=None
            leader_id=msg.body.src
            current_term=msg.body.term

        #check if any existing entries have diferent terms than the received ones
        for i in range(len(msg.body.entries)):
            if log[msg.body.preLogIndex+i][1]!=msg.body.entries[i][1]:
                #delete everything in front
                log = log[:msg.body.preLogIndex+i-1]
                #redoo all the operations!! from the begining
                restore_kv_state()
                break

        dif = msg.body.prevLogIndex-len(log)
        #para cada elemento das entries a pardir do "fim" do log, dar append e fazer a opecarao
        for i in range(len(msg.body.entries[dif:])):
            command=msg.body.entries[dif+i]
            log.append(command)
            commit_command(command)

        # if leadercommit > commitIndex set commitIndex = min(leadercommit , index of last new entry)
        #log[-1][1] quase a certeza  que isto esta mal, mas nao estou abem a ver oqq devia ser, to be fixed in the future
        if msg.body.commit>commitIndex:
            #commitIndex=min(msg.body.commit, log[-1][1])
            commitIndex=min(msg.body.commit, len(log))
            restore_kv_state()

        reply(msg,type='AppendEntries',res=True,term=current_term,next=len(msg.body.entries))

    #leader
    #(bool) res; description if write was sucessfull or not
    #(int) next; tamanho do log enviado para o cliente
    elif msg.body.type == 'AppendEntriesRes':
        add_timestamp(msg.body.src)
        if (msg.body.res):
            #update next index and match index
            nextIndex[msg.body.src] += msg.body.next
            matchIndex[msg.body.src] = commitIndex
        else:
            nextIndex[msg.src] -=1
            send(node_id, msg.src, type='AppendEntries', term=current_term, value=log[nextIndex[dest]:])
        # verifica se ja ha um consenso de replies
        flag = True
        maxn = commitIndex
        majority = len(node_ids)/2+1
        #poe em maxn o N maximo tal que existe um consenso de que commitIndex=N
        while(flag):
            #se ha consenso deste commit, da tbm o lider o commit
            if count_commit_index_consensus(maxn+1)>majority:
                maxn+=1
                commit_command(log[maxn])
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
            if ( votedFor != None or votedFor==msg.src ) and msg.body.lastLofIndex==len(log) and msg.body.lastLogTerm == log[-1][1]:
                votedFor = msg.body.src
                current_term=msg.body.term
                reply(msg,type='RequestVoteRes',term=current_term,res=False)

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