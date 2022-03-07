#!/usr/bin/env python

# 'echo' workload in Python for Maelstrom
# with an addtional custom MyMsg message

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from ms import send, receiveAll, reply, exitOnError

logging.getLogger().setLevel(logging.DEBUG)
executor=ThreadPoolExecutor(max_workers=1)

#key -> (value,timestamp)
dict = {}

global lock = threading.Lock
global timestamp = 0

global watingfor = 0
global arrived = 0
global currentValue
global currentTS
global inquisitorMsg
global quor


def handle(msg):
    # State
    global node_id, node_ids
    # Message handlers
    if msg.body.type == 'init':
        node_id = msg.body.node_id
        node_ids = msg.body.node_ids
        logging.info('node %s initialized', node_id)
        reply(msg, type='init_ok')

    elif msg.body.type == 'read':
        #COMECA O READ QUORUM
        n = divideRU(node_ids.len(),2)
        if waitingfor!=arrived:
            #mandar mensagem de erro ao inquisitor node
            reply(inquisitorMsg, type='error', code = 11)

        #resset das variaveis
        inquisitorMsg = msg
        waitingfor = n
        arrived = 0
        quor = getQuor(node_ids,n)
        key = msg.body.key
        getWriteQuorum(quor,key)

    elif msg.body.type == 'write':
        # escreve o key value pair 
        key = msg.body.key
        value = msg.body.value
        dict.update( {key : {value,timestamp} } )
        reply(msg, type='write_ok')

        for dest in node_ids:
            if dest != node_id:
                send(node_id, dest, type='MyWrite', key=key, value=value)

    elif msg.body.type == 'GetQ':
        if lock.aquire(False):
            reply(msg, type='GetQReplyFailed')
        key =  msg.body.key
        valuepair = dict[key]
        reply(msg, type='GetQReply', value=valuepair)

    elif msg.body.type == 'GetQReply':
        if arrived == waitingfor:
            ##responder ao gajo original com o ultimo valor
            reply(inquisitorMsg, type='read_ok', value = currentValue)
            #free aos lpcks

        {value,ts} = msg.body.value
        arrived++
        if arrived == 1 or currentTS<ts:
            currentTS=ts
            currentValue=value

    elif msg.body.type == 'ReleaseLock':
        #releases self lock
        lock.release()

   else:
        logging.warning('unknown message type %s', msg.body.type)

#send a message to a Write Quorum
def sendToWriteQ(Wq, message, node_id, key, value):
    for dest in Wq:
        send(node_id,dest, type='WriteQ', key=key, value=value)

def getWriteQ(Wq, node_id, key):
    for dest in Wq:
        send(node_id,dest, type='GetQ', key=key)

# get n elements at ranom from the list, With excepion of its own
def getQuor(nodes, int n):
    random.shuffle(nodes)[:n]

def divideRU(int n, int d):
    return (n + (d-1))/d

def freeLocks(node_id,quor):
    for q in quor:
        send(node_id,q,type='ReleaseLock')

# Main loop
executor.map(lambda msg: exitOnError(handle, msg), receiveAll())

# schedule deferred work with:
# executor.submit(exitOnError, myTask, args...)

# schedule a timeout with:
# from threading import Timer
# Timer(seconds, lambda: executor.submit(exitOnError, myTimeout, args...)).start()

# exitOnError is always optional, but useful for debugging
