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

#executa e da commit a uma instrucao
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

async def only_commit(exec_result,db,og=False):
    logging.info('commiting msg nr'+ str(msg.body.msg_id) )

    ctx = await db.begin([k for op,k,v in msg.body.txn], msg.src+'-'+str(msg.body.msg_id))
    rs,wv,res = exec_result
    if res:
        await db.commit(ctx, wv)
        db.cleanup(ctx)
        if(og):
            reply(msg, type='txn_ok',txn=res)
        return True
    else:
        #nao precisa de enviar a mensagem de erro porque ja foi enviada quando a execucao falhou
        return False

#divides the dictionary in messages that happened before and after
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

#verifica se a execucao de um comando invalida a execucao dos comandos
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

#executes the comands for a given message
# retuns the result from the execution, None in case it failed
async def execute(msg,db):
    logging.info('executing msg nr'+ str(msg.body.msg_id) )

    ctx = await db.begin([k for op,k,v in msg.body.txn], msg.src+'-'+str(msg.body.msg_id))
    rs,wv,res = await db.execute(ctx, msg.body.txn)
    db.cleanup(ctx)
    if res:
        return (rs,wv,res)
    else:     
        return False

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
        result=item[2]
        #execucao falhou, devolve erro
        if result==False:
            reply(msg, type='error', code=14, text='transaction aborted')
            logging.warning("transaction aborted by node" + node_id)
            (rs,wv,res) = result
            logging.warning("rs,wv,res"+ rs +"\\" + wv + "\\" +res)
            pass
        # nao foi executado ainda
        elif result==None:
            await commit(msg,db,og)
            msgn+=1
        # ja foi executado, so é preciso dar commit
        else:
            await only_commit(result, db)
            msgn+=1 
        await trycommits(msgQ,db)
    else:
        # vamos ver oqq pode ser ja execurado
        await exec_ahead(msgQ,db)

#executa todos os comandos que conseguir
async def exec_ahead(msgQ,db):
    ks = []
    for n,(msg,og,exe) in msgQ.items():
        #se ja estiver executado, adiciona as chaves alteradas ao resultado
        if exe:
            ks.extend(exe[1])
            pass
        #ainda nao foi executado
        elif exe==None:
            #check se o set de chaves alteradas ate agora e o set de chaves que este comando utiliza nao intercetam
            if not compare_sets([k for op,k,v in msg.body.txn],ks):
                #pode: executa e adiciona as chaves a que se alterou o valor a ks
                result = await execute(msg, db)
                msgQ[n]=(msg,og,result)
                ks.extend(result[1])
            else:
                #nao pode: adiciona todas as keys dentro do txn ao ks
                ks.extend([ k for op,k,v in msg.body.txn])
        #comando falhou a ser executado, podemos ignorar este caso
        else:
            pass


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
        msgQ[msg.body.ts] = (msg.body.msg, node_id==msg.src, None)
        await trycommits(msgQ, db)
    
    elif msg.body.type == 'ts_ok':
        #for node in filter(lambda n: n!=node_id,node_ids)
        m = queue.pop(0)
        for node in node_ids:
            logging.info("Sending msg to be replicated, to" + node)
            send(node_id, node, type='txnRep', msg=m, ts=msg.body.ts)

    else:
        logging.warning('unknown message type %s', msg.body.type)

# Main loop
run(receiveAll(handle))
