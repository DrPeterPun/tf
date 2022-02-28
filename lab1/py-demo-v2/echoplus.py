#!/usr/bin/env python

# 'echo' workload in Python for Maelstrom
# with an addtional custom MyMsg message

import logging
from concurrent.futures import ThreadPoolExecutor
from ms import send, receiveAll, reply, exitOnError

logging.getLogger().setLevel(logging.DEBUG)
executor=ThreadPoolExecutor(max_workers=1)

dict = {}

def handle(msg):
    # State
    global node_id, node_ids

    # Message handlers
    if msg.body.type == 'init':
        node_id = msg.body.node_id
        node_ids = msg.body.node_ids
        logging.info('node %s initialized', node_id)
        reply(msg, type='init_ok')

    elif msg.body.type == 'echo':
        logging.info('echoing %s', msg.body.echo)
        reply(msg, type='echo_ok', echo=msg.body.echo)

        for dest in node_ids:
            if dest != node_id:
                send(node_id, dest, type='MyMsg', mydata='some data...')

    elif msg.body.type == 'MyWrite':
        key = msg.body.key
        value = msg.body.value
        dict.update({key : value})


    elif msg.body.type == 'read':
        # devolve a chave
        value = dict.get(msg.body.key)
        if value:
            reply(msg , type='read_ok', value=value)
        else:
            ##moreu
            pass
        
    elif msg.body.type == 'write':
        # escreve o key value pair 
        key = msg.body.key
        value = msg.body.value
        dict.update({key : value})
        reply(msg, type='write_ok')

        for dest in node_ids:
            if dest != node_id:
                send(node_id, dest, type='MyWrite', key=key, value=value)

    elif msg.body.type == 'cas':
        fr0m = getattr(msg.body,"from")
        to = msg.body.to
        key = msg.body.key 
        value = dict.get(key) 
       
        if not value:
            #erro de nao haver key
            reply(msg, type="error", code=22)
        elif value==fr0m:
            dict.update({key:to})
            reply(msg, type="cas_ok")
        
            for dest in node_ids:
                if dest != node_id:
                    send(node_id, dest, type='MyWrite', key=key, value=value)
        else:
            #erro de ps values serem diferentes
            reply(msg, type="error", code=20)

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