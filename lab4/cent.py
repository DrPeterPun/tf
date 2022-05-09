#!/usr/bin/env python

import logging
from asyncio import run, create_task, sleep

from ams import send, receiveAll, reply
from db import DB

logging.getLogger().setLevel(logging.DEBUG)

#master node

db = DB()
#dict saving uncommited commands ( origianl msg id : (msg, originalnode ) ) 
msgQ = {}
# nr of the last commited msg, id is "id" + msgn
msgn = 0


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
        db.cleanup(ctx)
        return False

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
    global master

    # Message handlers
    if msg.body.type == 'init':
        node_id = msg.body.node_id
        node_ids = msg.body.node_ids
        master = node_ids[0]
        logging.info('node %s initialized', node_id)

        reply(msg, type='init_ok')

    elif msg.body.type == 'txn':
        #msgs de replicacao
        #check if its master node
        if not node_id==master:
            send(msg.src,master,txn=msg.body.txn,type='txn')
        #for node in filter(lambda n: n!=node_id,node_ids):
        for node in node_ids:
            logging.info("Sending msg to be replicated, dest" + node)
            send(node_id, node, type='txnRep',msg=msg)
        await trycommits(msgQ,db)

    #replication msg or the commands
    #ads command to q then tries to execute 
    elif msg.body.type == 'txnRep':
        #added msg to the Q
        msgQ[msg.body.msg.body.msg_id]= (msg.body.msg,node_id==msg.src)
        await trycommits(msgQ,db)

    else:
        logging.warning('unknown message type %s', msg.body.type)

# Main loop
run(receiveAll(handle))
