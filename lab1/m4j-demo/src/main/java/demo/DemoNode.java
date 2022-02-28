package demo;

import pt.inesctec.m4j.Network;
import pt.inesctec.m4j.Node;
import pt.inesctec.m4j.protocol.Message;
import pt.inesctec.m4j.workload.Echo;

import java.util.concurrent.Executors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Simple 'echo' workload in Java for Maelstrom, with inversion-of-control
 * using the abstract Node class.
 */
public class DemoNode extends Node {

    // Message handlers
    @Override
    public void accept(Message msg) {
        if (msg.body() instanceof Echo body) {
            // Handle workload message
            logger.info("echoing {}", body.echo());
            send(new Message(msg.dest(), msg.src(), new Echo.Ok(body.echo(), next_id(), body.msg_id())));

        } else {
            // Default handler
            super.accept(msg);
        }
    }

    // Setup
    public DemoNode() {
        super(new Network(Echo.class), Executors.newScheduledThreadPool(1));
    }
    public static void main(String[] args) {
        new DemoNode().run();
    }

    private Logger logger = LoggerFactory.getLogger(DemoNode.class);
}
