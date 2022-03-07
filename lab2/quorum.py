#!/usr/bin/env python

# 'echo' workload in Python for Maelstrom
# with an addtional custom MyMsg message

import logging
import threading
import random
from concurrent.futures import ThreadPoolExecutor
from ms import send, receiveAll, reply, exitOnError

logging.getLogger().setLevel(logging.DEBUG)
executor=ThreadPoolExecutor(max_workers=1)

#key -> (value,timestamp)
dict = {}

def handle(msg):
    # State
    global node_id, node_ids
    global lock
    lock= threading.Lock()
    global timestamp
    timestamp = 0

    global watingfor
    waitingfor = 0
    global arrived
    arrived = 0
    global currentValue
    global currentTS
    global inquisitorMsg
    global quor

    # Message handlers
    if msg.body.type == 'init':
        node_id = msg.body.node_id
        node_ids = msg.body.node_ids
        logging.info('node %s initialized', node_id)
        reply(msg, type='init_ok')
            # message from "outside" with a read order
    # gets a read quorum
    elif msg.body.type == 'read':
        quor = getQuor(node_ids)
        key = msg.body.key
        getReadQ(quor,node_id,key,msg)

    # message from "outside" with a write order
    # get a write quorum and write to it
    elif msg.body.type == 'write':
        quor = getQuor(node_ids)
        key = msg.body.key
        getWriteQ(quor,node_id,key,msg)

    elif msg.body.type == 'MyWrite':
        ts = msg.body.timestamp
        key = msg.body.key
        value = msg.body.value
        dict.update(key,(value,timestamp))
        lock.release()

    #getQuorum message, this node tries to get a lock and replyes with the current value
    elif msg.body.type == 'GetReadLock':
        if not lock.acquire():
            reply(msg, type='GetQReplyFailed')
        key =  msg.body.key
        valuepair = dict[key]
        reply(msg, type='GetReadReply', value=valuepair)

    elif msg.body.type == 'GetWrit  Lock':
        if not lock.acquire():
            reply(msg, type='GetQWriteFailed')
        key =  msg.body.key
        valuepair = dict[key]
        reply(msg, type='GetWriteReply', value=valuepair)

    #replyes to original get Quorum message; received by the node that started the transaction
    #checks if the number of messages is ==n, and if it is the read was successful
    elif msg.body.type == 'GetReadReply':
        if arrived == waitingfor:
            ##responder ao gajo original com o ultimo valor
            reply(inquisitorMsg, type='read_ok', value = currentValue)
            freeLocks(node_id,quor)
            #free aos lpcks

        (value,ts) = msg.body.value
        arrived+=1
        if arrived == 1 or currentTS<ts:
            currentTS=ts
            currentValue=value

    elif msg.body.type == 'GetWriteReply':
        if arrived == waitingfor:
            # mandar ao quorum pedidos de escrita
            currentTS+=1
            writeToQuor(quor,node_id)
            reply(inquisitorMsg, type='write_ok', value = currentValue)

        (value,ts) = msg.body.value
        arrived+=1
        if arrived == 1 or currentTS<ts:
            currentTS=ts

    #order to release the lock
    elif msg.body.type == 'ReleaseLock':
        #releases self lock
        lock.release()

    else:
        logging.warning('unknown message type %s', msg.body.type)

def getReadQ(Wq, node_id, key,msg):
    #COMECA O READ QUORUM
    n = divideRU(len(node_ids),2)
    #resset das variaveis
    inquisitorMsg = msg
    waitingfor = n
    arrived = 0
    quor = getQuor(node_ids)
    key = msg.body.key
    if waitingfor!=arrived:
        #recebeu uma mensagem de write mas uma escrita esta em progresso
        #mandar mensagem de erro a cena que perguntou
        reply(msg, type='error', code = 11)

    getReadLocks(node_id,quor,key)

def getWriteQ(Rq, node_id, key, msg):
    #COMECA O WRITE QUORUM
    n = divideRU(len(node_ids),2)
    #resset das variaveis
    inquisitorMsg = msg
    waitingfor = n
    arrived = 0
    quor = getQuor(node_ids)
    key = msg.body.key
    writeValue = msg.body.value
    if waitingfor!=arrived:
        #recebeu uma mensagem de write mas uma escrita esta em progresso
        #mandar mensagem de erro a cena que perguntou
        reply(msg, type='error', code = 11)

    getWriteLocks(node_id,quor,key)

def writeToQuor(Wq, node_id):
    for q in Wq:
        send(node_id, q, type='MyWrite',key=key, value=currentValue,timestamp = currentTS)

# get n elements at ranom from the list, With excepion of its own
def getQuor(nodes):
    n = divideRU(len(nodes),2)
    logging.info("n: " +  str(n))
    random.shuffle(nodes)
    return nodes[:n]

def divideRU( n,  d):
    return int((n + (d-1))/d)

def freeLocks(node_id,quor):
    for q in quor:
        send(node_id,q,type='ReleaseLock')

def getReadLocks(node_id,quor,key):
    for q in quor:
        send(node_id,q,type='GetReadLock',key=key)

def getWriteLocks(node_id,quor):
    for q in quor:
        send(node_id,q,type='GetWriteLock')



# Main loop
executor.map(lambda msg: exitOnError(handle, msg), receiveAll())

# schedule deferred work with:
# executor.submit(exitOnError, myTask, args...)

# schedule a timeout with:
# from threading import Timer
# Timer(seconds, lambda: executor.submit(exitOnError, myTimeout, args...)).start()

# exitOnError is always optional, but useful for debugging
