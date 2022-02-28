package demo;

import pt.inesctec.m4j.*;
import pt.inesctec.m4j.workload.Echo;
import pt.inesctec.m4j.protocol.Init;
import pt.inesctec.m4j.protocol.Message;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 'echo' workload in Java for Maelstrom with an additional custom MyMsg message
 */
public class DemoPlus {

    // Message types
    public record MyMsg(int msg_id, String data) {};

    public static void main(String[] args) throws Exception {
        var net = new Network(Echo.class, DemoPlus.class);

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

                for(var dest: node_ids)
                    if (!dest.equals(node_id))
                        net.send(new Message(node_id, node_ids.get(next_id%node_ids.size()), new MyMsg(next_id++, "Some data...")));

            } else if (msg.body() instanceof MyMsg body) {

                logger.info("custom message from peer {}", msg.src());

            } else {
                
                logger.warn("unknown message type {}", msg.body().getClass().getName());
            }
        }
    }

    private static Logger logger = LoggerFactory.getLogger(DemoPlus.class);
}
