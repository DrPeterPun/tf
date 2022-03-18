#!/usr/bin/env python

# 'lin-kv' workload in Python for Maelstrom

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from random import sample
from ms import send, receiveAll, reply, exitOnError

logging.getLogger().setLevel(logging.DEBUG)
executor=ThreadPoolExecutor(max_workers=1)
# {key: {value, version}}
kv_store = {}
msg_queue = []
# {id: {msg, value, version, total, recv}}
read_waiting = {}
# {id: {msg, [locked], value, version, total, confirmed, failed, is_cas}}
write_waiting = {}

# Msg Types:
#   - init: Maelstrom init request

#   - read: Maelstrom read request
#   - read_quorum: Performs a read operation. Recieves desiered key. Returns read_ok to requester node.
#   - read_ok: Maelstrom read reply. Contains id, value and timestamp if response to another node.
#   - read_no_key: Read error return in case key is not found

#   - write: Maelstrom write request
#   - write_lock: Request a write lock. Recieves desiered key, returns current key and timestamp
#   - write_quorum: Performs a write operation. Recieves desiered key, value and timestamp. Returns write_ok, releases lock
#   - write_lock_release: Releases a write lock. Recieves desiered key
#   - write_ok: Maelstrom write reply. Contains id if response to another node.
#   - write_lock_ok: Reply to a write_lock request.
#   - write_no_lock: Error in case key is already locked. Returns write_id

def quorum_pick(node_ids):
    size = (len(node_ids) + 1) / 2
    return sample(node_ids, int(size))

def handle(msg):
    global node_id, node_ids, write_id, read_id

    # Message handlers
    if msg.body.type == 'init':
        node_id = msg.body.node_id
        node_ids = msg.body.node_ids
        logging.info('node %s initialized', node_id)
        write_id = 0
        read_id = 0
        reply(msg, type='init_ok')

    elif msg.body.type == 'read':
        # Pick a read quorum
        quorum = quorum_pick(node_ids)
        # Request Value from each quorum node
        for dest in quorum:
            send(node_id, dest, type='read_quorum', key=msg.body.key, read_id=read_id)
        # Create process status information
        read_waiting.update({read_id: {'msg': msg, 'value': None, 'version': None, 'recv': 0, 'total': len(quorum)}})
        read_id = read_id + 1

    elif msg.body.type == 'read_quorum':
        # Gets value from storage
        value = kv_store.get(msg.body.key)
        if value == None:
            # Reply in case of non existent key
            reply(msg, type='read_no_key', read_id=msg.body.read_id, key=msg.body.key)
        else:
            # Reply with value and version
            reply(msg, type='read_ok', read_id=msg.body.read_id, key=msg.body.key, value=value['value'], version=value['version'])

    elif msg.body.type == 'read_ok' or msg.body.type == 'read_no_key':
        # Gets process info
        queue = read_waiting[msg.body.read_id]
        # If msg indicates a successful read
        if msg.body.type == 'read_ok':
            # Compares versions and updates value if the recieved value is newer
            if queue['version'] == None or (msg.body.version != None and msg.body.version > queue['version']):
                queue['value']= msg.body.value
                queue['version'] = msg.body.version
        queue['recv'] = queue['recv'] + 1
        # If all quorum nodes replied
        if queue['recv'] == queue['total']:
            # If the key did not exist in any node
            if queue['value'] == None:
                reply(queue['msg'], type='error', code=20, text="Invalid Key")
            # If key was found successful, return the most recent value
            else:
                reply(queue['msg'], type='read_ok', value=queue['value'])
            # Cleanup process info
            read_waiting.pop(msg.body.read_id, None)
        # If some nodes haven't replied yet, update process info
        else:
            read_waiting.update(queue)

    elif msg.body.type == 'write' or msg.body.type == 'cas':
        # Pick write quotum
        quorum = quorum_pick(node_ids)
        # Request each node to lock the key we want to write on
        for dest in quorum:
            send(node_id, dest, type='write_lock', key=msg.body.key, write_id=write_id)
        # Create process status information
        write_waiting.update({write_id: {'msg': msg, 'version': None, 'value': None, 'locked': [], 'total': len(quorum), 'confirmed': 0, 'failed': False, 'cas': msg.body.type == 'cas'}})
        write_id = write_id + 1

    elif msg.body.type == 'write_lock':
        # Retrieve value from storage
        value = kv_store.get(msg.body.key)
        # If value isn't present, lock the key anyway
        if value == None:
            kv_store.update({msg.body.key: {'value': None, 'version': None }})
            # Reply that the process locked this key with success
            reply(msg, type='write_lock_ok', write_id=msg.body.write_id, key=msg.body.key, version=None, value=None)
        else:
            kv_store.update(value)
            # Reply that the process locked this key with success
            reply(msg, type='write_lock_ok', write_id=msg.body.write_id, key=msg.body.key, version=value['version'], value=value['value'])

    elif msg.body.type == 'write_lock_ok':
        # Retrieve process info
        queue = write_waiting[msg.body.write_id]
        # Record that the node has replied to the lock request
        queue['locked'].append(msg.src)
        # If lock was successful, update version and value if those are more recent than the one we have
        if queue['version'] == None or (msg.body.version != None and msg.body.version > queue['version']):
            queue['version'] = msg.body.version
            queue['value'] = msg.body.value
        # If all nodes replied to the lock request
        if len(queue['locked']) == queue['total']:
            # If key didn't exist in any node
            if queue['version'] == None:
                # In case of a CAS request, we need to reply that the key wasn't present
                if queue['cas']:
                    queue['failed'] = True
                    error_code = 20
                    error_msg = "Invalid Key"
                # In case of a write, we want to write anyway
                else:
                    queue['version'] = 0
            # Process if this is a CAS request
            if queue['cas']:
                # Adjust naming to match CAS request with write request
                queue['msg'].body.value = queue['msg'].body.to
                # Check if CAS from value matches the value we have stored
                if queue['value'] != getattr(queue['msg'].body, "from"):
                    queue['failed'] = True
                    error_code = 22
                    error_msg = "Invalid Cas From value"

            # If locking was success, write to quorum nodes ( with no locks, its always sucessfull)
            for dest in queue['locked']:
                send(node_id, dest, type='write_quorum', key=queue['msg'].body.key, value=queue['msg'].body.value, version=queue['version'] + 1, write_id=msg.body.write_id)
                # If some nodes haven't reply, wait for all replies
        else:
            write_waiting.update(queue)

    elif msg.body.type == 'write_quorum':
        # Retrive value from storage
        value = kv_store.get(msg.body.key)
        # Check if lock if correct, else ignore request
        if value['lock'] == msg.body.write_id:
            kv_store.update({msg.body.key: {'value': msg.body.value, 'version': msg.body.version, 'lock': None}})
            reply(msg, type='write_ok', write_id=msg.body.write_id)

    elif msg.body.type == 'write_ok':
        # Retrive process info
        queue = write_waiting[msg.body.write_id]
        # Increment number of confirmations
        queue['confirmed'] = queue['confirmed'] + 1
        # If all nodes confirmed the write, reply to maelstrom
        if queue['confirmed'] == queue['total']:
            if queue['cas']:
                reply(queue['msg'], type='cas_ok')
            else:
                reply(queue['msg'], type='write_ok')
            # Cleanup process info
            write_waiting.pop(msg.body.write_id, None)
        # Else, update process info
        else:
            write_waiting.update(queue)

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
