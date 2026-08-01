package com.xv6.router;

import com.xv6.shared.CommandServer;
import com.xv6.shared.LogLevels;
import com.xv6.shared.Stats;
import com.xv6.shared.StopEvent;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.logging.Logger;

/** Entry point, reconnect loop. Port of router_py's router/main.py. */
public final class RouterMain {

    private static final Logger logger = Logger.getLogger(RouterMain.class.getName());

    private RouterMain() {
    }

    public static void run(RouterConfig cfg, StopEvent stopEvent, Stats statsIn) throws Exception {
        Stats stats = statsIn != null ? statsIn : new Stats(cfg.yellowThresholdSeconds());

        // MUST come before CommandServer(...): CommandServer adds a LogBuffer handler to the
        // root logger, and setting the level after that still works, but doing it first mirrors
        // router_py's ordering requirement (there, a late basicConfig call is a no-op once the root
        // logger already has handlers - not an issue for java.util.logging, but kept in the same
        // order for parity).
        Logger.getLogger("").setLevel(LogLevels.parse(cfg.logLevel()));

        CommandServer cmd = new CommandServer(
                cfg.commandPort(), stats, stopEvent, cfg.commandBindHost(), cfg.commandAuthToken());

        AtomicReference<Dispatcher> activeDispatcher = new AtomicReference<>();

        cmd.register("/dispatcher/purge", List.of("POST"), true, exchange -> {
            Dispatcher dispatcher = activeDispatcher.get();
            if (dispatcher == null) {
                CommandServer.sendJson(exchange, 503, Map.of("error", "no active session"));
                return;
            }
            CommandServer.sendJson(exchange, 200, dispatcher.purge());
        });

        cmd.start();

        Upstream.UpstreamServer srvSock = null;
        if ("server".equals(cfg.upstream().mode())) {
            srvSock = new Upstream.UpstreamServer(cfg.upstream());
        }

        try {
            Random random = new Random();
            while (!stopEvent.isSet()) {
                RouterSession session;
                try {
                    session = RouterSession.connect(cfg, stats, stopEvent);
                } catch (IOException e) {
                    logger.warning("failed to connect downstream: " + e.getMessage());
                    waitReestablish(stopEvent, cfg, random);
                    continue;
                }

                activeDispatcher.set(session.dispatcher);
                session.runUntilDisconnect(srvSock);
                activeDispatcher.set(null);

                if (!stopEvent.isSet()) {
                    // Jitter avoids multiple routers sharing a downstream/crypto host
                    // reconnecting in lockstep.
                    waitReestablish(stopEvent, cfg, random);
                }
            }
        } finally {
            if (srvSock != null) {
                srvSock.close();
            }
        }
    }

    private static void waitReestablish(StopEvent stopEvent, RouterConfig cfg, Random random)
            throws InterruptedException {
        double jitter = random.nextDouble() * cfg.reconnectJitterSeconds();
        long millis = Math.round((cfg.reestablishSeconds() + jitter) * 1000);
        stopEvent.waitFor(millis, TimeUnit.MILLISECONDS);
    }

    public static void main(String[] args) throws Exception {
        String configPath = null;
        for (int i = 0; i < args.length; i++) {
            if ("--config".equals(args[i]) && i + 1 < args.length) {
                configPath = args[i + 1];
            }
        }
        if (configPath == null) {
            throw new IllegalArgumentException("usage: RouterMain --config <path>");
        }
        RouterConfig cfg = RouterConfig.fromFile(configPath);
        try {
            run(cfg, new StopEvent(), null);
            // com.sun.net.httpserver.HttpServer's internal dispatcher thread is not a daemon
            // thread (confirmed by testing: the process stayed alive after /stop with only that
            // thread left), so unlike router_py (where every thread genuinely is a daemon thread and
            // the interpreter exits on its own), this JVM needs an explicit exit once run()
            // returns. run() itself must stay exit-free, since RouterFullStackTest calls it
            // directly in-process and a System.exit() here would kill the test JVM too.
            System.exit(0);
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }
}
