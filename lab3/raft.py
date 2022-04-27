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
        if (not is_leader()):
            return

        init_timestamps(node_ids)
        for node in node_ids:
            if not node==leader_id:
                recursive_heartbeats(node,MIN_HB,MAX_HB)
        nextIndex = [len(log) for _ in range(len(node_ids))]
        matchIndex = [0 for _ in range(len(node_ids))]]

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
    #not present yet //////////// leaderID
    elif msg.body.type == 'AppendEntries':
        #term receives less than current term
        if msg.body.term<currentTerm:
            msg.reply(type='AppendEntriesRes',res=False,term=currentTerm)
            return
        # terms not matching
        else if log[msg.body.prevLogIndex][1]!=msg.body.entries[0][1]
            msg.reply(type='AppendEntriesRes',res=False,term=currentTerm)
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
        if msg.body.commit>commitIndex:
            commitIndex=min(msg.body.commit, log[-1][1])

        msg.reply(type='AppendEntries',res=True,term=CurrentTerm,next=len(msg.body.entries))

    #leader
    #(bool) res; description if write was sucessfull or not
    #(int) next; tamanho do log enviado para o cliente
    elif msg.body.type == 'AppendEntriesRes':
        add_timestamp(msg.src)
        if (msg.body.res):
            #update next index and match index
            nextIndex[msg.src] += msg.body.next
            matchIndex[msg.src] = commitIndex
            pass
        else:
            nextIndex[msg.src] -=1
            send(node_id, msg.src, type='AppendEntries', term=current_term, value=log[nextIndex[dest]:])

    else:
        logging.warning('unknown message type %s', msg.body.type)

# Main loop
executor.map(lambda msg: exitOnError(handle, msg), receiveAll())

#checks if current node is the leader, returns True if it IS the leadder
#not the leader -> reply with error code 11 and return false
def is_leader(msg=None):
    if(node_id != leader_id):
        if (msg!=None):
            reply(msg, type="error",code=11 )
        return False
    return True

#timestamp_dict , node_id
def check_timestamp(node_id):
    return timeout_dict[node_id]-time.time_ns()<MAX_TIME_DIF

def add_timestamp(node_id):
    timeout_dict[node_id]=time.time_ns()

def init_timestamps(node_ids):
    t = time.time_ns()
    for id in node_ids:
        timeout_dict[id]=t

def heartbeat(dest):
    send(node_id, dest, type='AppendEntries', term=current_term,prevLogIndex = nextIndex[dest]-1 ,entries=log[nextIndex[dest]:],commit=commitIndex)

def recursive_heartbeats(dest,min_time,max_time):
    if node_id==leader_id:
        heartbeat(dest)
        sec = randrange(min_time,max_time)
        Timer(sec, lambda: executor.submit(reccursive_heartbeats,min_time,max_time))

# schedule deferred work with:
# executor.submit(exitOnError, myTask, args...)

# schedule a timeout with:
# from threading import Timer
# Timer(seconds, lambda: executor.submit(exitOnError, myTimeout, args...)).start()

# exitOnError is always optional, but useful for debugging
