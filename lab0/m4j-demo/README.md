# Demo node app in Java for Maelstrom

# Setup

Download and unpack [Maelstrom release package](https://github.com/jepsen-io/maelstrom/releases) to obtain `maelstrom.jar`.

Build demo application with:

	$ ./gradlew installDist

You may change `mainClassName`in `build.gradle`to select alternative implementations.

## Run

Run system simulation with:

	$ java -jar maelstrom.jar test --bin ./build/install/m4j-demo/bin/m4j-demo -w echo --time-limit 10

To observe results, launch web server with: 

	$ java -jar maelstrom.jar serve
