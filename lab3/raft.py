#!/usr/bin/env python

# 'echo' workload in Python for Maelstrom
# with an addtional custom MyMsg message

import logging
from concurrent.futures import ThreadPoolExecutor
from ms import send, receiveAll, reply, exitOnError
from threading import Timer

logging.getLogger().setLevel(logging.DEBUG)
executor=ThreadPoolExecutor(max_workers=1)
leader_id = node_ids[0]

# key value store (key: value)
kvstore = {}
#nr do mandato
current_term = 0
#lista de pares (pedido, current term)
log = []
currentIndex = 1
#em que lider votou, (candidateId)
votedFor = None
# indice da maior entrada que foi commited
commitIndex = 0
# indice da maior entrada aplicada
lasApplied = 0

#LEADER ONLY
#indice da proxima entrada a ser ENVIADA a cada servidor (init a laslogindex+1)
nextIndex = None
#indice da entrada com indice maior REPLICADA em casa servidor (init a 0)
matchIndex = None
#timeout dict,guarda: (node_id : timestamp)
timeout_dict= {}
#tempo maximo sem resposta de um nodo para o considerar ofline 0.1s
MAX_TIME_DIF = 100000000
MIN_HB = MAX_TIME_DIF/5
MAX_HB = MAX_TIME_DIF/2


def handle(msg):
    # State
    global node_id, node_ids

    # Message handlers
    if msg.body.type == 'init':
        node_id = msg.body.node_id
        node_ids = msg.body.node_ids
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

        log.append( ( 'write',(key,value) ,current_term) )
        lastLogIndex = len(log)
        for dest in node_ids:
            if dest != node_id and lastLogindex>= nextIndex[dest]:
                send(node_id, dest, type='AppendEntries', term=current_term,prevLogIndex = nextIndex[dest]-1 ,entries=log[nextIndex[dest]:],commit=commitIndex)

    #follower
    #entries; list og logs to commit to local log
    #term; termo do lider
    #prevLogIndex; indice do Log imediatamente antes ao primeiro enviado
    #prevLogTerm; termo da primeira entrada do prevLogIndex
    #commit; commitIndex do lidera
    #not present yet //////////// leaderID, Se receberes uma msg com um leader id diferente alteras o leader id para ser esse? ( caso o term seja maior do que o que tens atualmente)
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    elif msg.body.type == 'AppendEntries':
        add_timestamp(msg.src)
        #term receives less than current term
        if msg.body.term<current_term:
            msg.reply(type='AppendEntriesRes',res=False,term=current_term)
            return
        # terms not matching
        elif log[msg.body.prevLogIndex][1]!=msg.body.entries[0][1]:
            msg.reply(type='AppendEntriesRes',res=False,term=current_term)
            return

        #check if any existing entries have diferent terms than the received ones
        for i in range(len(msg.body.entries)):
            if log[msg.body.preLogIndex+i][1]!=msg.body.entries[i][1]:
                ##delete everything in front
                log = log[:msg.body.preLogIndex+i-1]
                break

        dif = msg.body.prevLogIndex-len(log)
        #para cada elemento das entries a pardir do "fim" do log, dar append
        for i in range(len(msg.body.entries[dif:])):
            log.append(msg.body.entries[dif+i])

        # if leadercommit > commitIndex set commitIndex = min(leadercommit , index of last new entry)
        #log[-1][1])quase a certeza  que isto esta mal, mas nao estou abem a ver oqq devia ser, to be fixed in the future
        #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        if msg.body.commit>commitIndex:
            commitIndex=min(msg.body.commit, log[-1][1])

        msg.reply(type='AppendEntries',res=True,term=current_term,next=len(msg.body.entries))

    #leader
    #(bool) res; description if write was sucessfull or not
    #(int) next; tamanho do log enviado para o cliente
    elif msg.body.type == 'AppendEntriesRes':
        add_timestamp(msg.src)
        if (msg.body.res):
            #update next index and match index
            nextIndex[msg.src] += msg.body.next
            matchIndex[msg.src] = commitIndex
        else:
            nextIndex[msg.src] -=1
            send(node_id, msg.src, type='AppendEntries', term=current_term, value=log[nextIndex[dest]:])

    #candidate
    #term
    #candidateId
    #lastLogIndex
    #lasLogTerm
    elif msg.body.type == 'RequestVote':
        add_timestamp(msg.src)
        if msg.term<current_term:
            msg.reply(type='RequestVoteRes', term=current_term, res= False)
        else:
            if ( votedFor != None or votedFor==msg.src ) and msg.lastLofIndex==len(log) and msg.lastLogTerm == log[-1][1]:
                voteFor = msg.src


    else:
        logging.warning('unknown message type %s', msg.body.type)

# Main loop
executor.map(lambda msg: exitOnError(handle, msg), receiveAll())

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

#timestamp_dict , node_id
#check if a node is alive
def check_timestamp(node_id):
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
        sec = randrange(min_time,max_time)
        Timer(sec, lambda: executor.submit(reccursive_heartbeats,min_time,max_time))

#periodicly checls if the leadder is alive. if its not starts a vote for new leader
def leader_alive_checker():
    if not is_leader():
        if not check_timestamp(leader_id):
            request_vote()
        sec = randrange(min_time,max_time)
        Timer(sec, lambda: executor.submit(leader_alive_checker,min_time,max_time))

#starts a neew vote as
def request_vote():
    send(node_id, dest, type='RequestVote', term=current_term,prevLogIndex = nextIndex[dest]-1 ,entries=log[nextIndex[dest]:], candidateId=node_id)

# schedule deferred work with:
# executor.submit(exitOnError, myTask, args...)

# schedule a timeout with:
# from threading import Timer
# Timer(seconds, lambda: executor.submit(exitOnError, myTimeout, args...)).start()

# exitOnError is always optional, but useful for debugging
