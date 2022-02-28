package demo;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import pt.inesctec.m4j.Network;
import pt.inesctec.m4j.protocol.Init;
import pt.inesctec.m4j.protocol.Message;
import pt.inesctec.m4j.workload.Echo;

import java.util.List;

/**
 * Simple 'echo' workload in Java for Maelstrom
 */
public class Demo {

    public static void main(String[] args) throws Exception {
        var net = new Network(Echo.class);

        // State
        String node_id = null;
        List<String> node_ids = null;
        int next_id = 1;

        // Message handlers
        Message msg;
        while((msg = net.receive()) != null) {
            if (msg.body() instanceof Init body) {

                node_id = body.node_id();
                node_ids = body.node_ids();
                logger.info("node {} initialized", node_id);
                net.send(new Message(node_id, msg.src(), new Init.Ok(next_id++, body.msg_id())));

            } else if (msg.body() instanceof Echo body) {

                logger.info("echoing {}", body.echo());
                net.send(new Message(node_id, msg.src(), new Echo.Ok(body.echo(), next_id++, body.msg_id())));

            } else {
                
                logger.warn("unknown message type {}", msg.body().getClass().getName());
            }
        }
    }

    private static Logger logger = LoggerFactory.getLogger(Demo.class);
}
