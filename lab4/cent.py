#!/usr/bin/env python

import logging
from asyncio import run, create_task, sleep

from ams import send, receiveAll, reply
from db import DB

logging.getLogger().setLevel(logging.DEBUG)

#master node

#commands that still dont have an id, Queue
queue = []

#database manager
db = DB()
#dict saving uncommited commands ( origianl msg id : (msg, originalnode,result from execution ) ) 
msgQ = {}
# nr of the last commited msg, id is "id" + msgn
msgn = -1

#da commit a uma instrucao
#se og=True, envia a mensagem de confirmacao ao cliente
async def commit(msg,db,og=False):
    logging.info('commiting msg nr'+ str(msg.body.msg_id) )

    ctx = await db.begin([k for op,k,v in msg.body.txn], msg.src+'-'+str(msg.body.msg_id))
    rs,wv,res = await db.execute(ctx, msg.body.txn)
    if res:
        await db.commit(ctx, wv)
        db.cleanup(ctx)
        if(og):
            reply(msg, type='txn_ok',txn=res)
        return True
    else:
        if og:
            reply(msg, type='error', code=14, text='transaction aborted')
        logging.warning("transaction aborted by node" + node_id)
        logging.warning("rs,wv,res"+ rs +"\\" + wv + "\\" +res)
        db.cleanup(ctx)
        return False

def divide_dict(msgQ,msgn):
    before = {}
    after = {}
    for m in msgQ.items():
        if msgn<m[0]:
            before[m[0]]=m[1]
        elif msgn>m[0]:
            after[m[0]]=m[1]
        else:
            logging.warning("something went wrong with the message queue")
    return(before,after)

#lista de pares k,v -> lista de k
def wvtok(wv):
    return list(map(lambda a: a[0],wv))
      
#true if unions is not empty
def compare_sets(a,b):
    return len([value for value in a if value in b])>0

#checks if a command can be executed
def check_before(msg,msgQ):
    before,=divide_dict(msg.body.ts,msgQ)
    msgk=[k for op,k,v in msg.body.txn]
    for m in before:
        #se houver intecessao nos sets retornamos falso
        if compate_sets(wvtok(m[2][1]),msgk):
            return False
    return True

#verifica se a execucao de um comando inalida a execucao dos comandos
#posteriores
def check_after(wv,msgQ):
    wk = wvtok(wv)
    _,after=divide_dict(msg.body.ts,msgQ)
    for n,msg in after.items():
        msgk=[k for op,k,v in msg.body.txn]
        # caso o comando futuro utilize de um valor que foi escrito pelo comando
        # que estamos agora a analisar, mudamos a execucao para False
        if compare_sets(wk,msgk):
            m,og,res = msgQ[n]
            msgQ[n]= (m,og,None)

#executes a the comands for a given message
async def execute(msg,db):
    logging.info('commiting msg nr'+ str(msg.body.msg_id) )

    ctx = await db.begin([k for op,k,v in msg.body.txn], msg.src+'-'+str(msg.body.msg_id))
    rs,wv,res = await db.execute(ctx, msg.body.txn)
    if res:
        return (rs,wv,res)
    else:
        return None

# faz o maximo numero de commits possivel.
async def trycommits(msgQ,db):
    global msgn
    #check if the next msg exists in the Q
    item = msgQ.pop(msgn+1,False)
    #the msg exists, so we commit it
    logging.info("cehcking if we can commit the msg: " + str(msgn+1))
    logging.info("msgs" + str(msgQ))
    if item:
        msg=item[0]
        og=item[1]
        await commit(msg,db,og)
        msgn+=1
        await trycommits(msgQ,db)
    else:
        return

async def handle(msg):
    # State
    global node_id, node_ids
    global db

    # Message handlers
    if msg.body.type == 'init':
        node_id = msg.body.node_id
        node_ids = msg.body.node_ids
        logging.info('node %s initialized', node_id)

        reply(msg, type='init_ok') 

    elif msg.body.type == 'txn':
        #asks for the msg number
        send(node_id,'lin-tso',type='ts')
        #adds the command to the queue
        queue.append(msg)

    #replication msg or the commands
    #ads command to q then tries to execute 
    elif msg.body.type == 'txnRep':
        #added msg to the Q
        msgQ[msg.body.ts] = (msg.body.msg,node_id==msg.src)
        await trycommits(msgQ,db)
    
    elif msg.body.type == 'ts_ok':
        #for node in filter(lambda n: n!=node_id,node_ids)
        m = queue.pop(0)
        for node in node_ids:
            logging.info("Sending msg to be replicated, to" + node)
            send(node_id, node, type='txnRep',msg=m,ts=msg.body.ts)

    else:
        logging.warning('unknown message type %s', msg.body.type)

# Main loop
run(receiveAll(handle))
