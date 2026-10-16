package com.focusledger.android;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.GZIPInputStream;
import static org.junit.Assert.*;

public class TransportTest {
    TestHttpServer primary, fallback; Config config; Transport transport;
    @Before public void setup() throws Exception {
        primary = TestHttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0); fallback = TestHttpServer.create(new java.net.InetSocketAddress("127.0.0.1",0),0);
        primary.start(); fallback.start(); config = new Config(); config.primary = url(primary); config.fallback = url(fallback);
        config.apiKey = "test-upload-key-123456789012345678901"; config.deviceName = "Android test"; config.scope = "test";
        transport = new Transport("a".repeat(64));
    }
    @After public void teardown() { primary.stop(0); fallback.stop(0); }
    private String url(TestHttpServer server) { return "http://127.0.0.1:"+server.getAddress().getPort(); }
    private void json(TestHttpServer.Exchange exchange, int status, String body) throws java.io.IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8); exchange.sendResponseHeaders(status,bytes.length); exchange.getResponseBody().write(bytes); exchange.close();
    }
    @Test public void failoverPreservesEventIdentityAndAuth() throws Exception {
        primary.createContext("/api/v1/usage/batches", e -> json(e,503,"{}"));
        AtomicInteger received = new AtomicInteger();
        fallback.createContext("/api/v1/usage/batches", e -> {
            try {
                JSONObject body = new JSONObject(new String(e.getRequestBody().readAllBytes(),StandardCharsets.UTF_8));
                assertEquals("stable-event",body.getJSONArray("events").getJSONObject(0).getString("id"));
                assertEquals("Bearer "+config.apiKey,e.getRequestHeaders().getFirst("Authorization")); assertEquals("a".repeat(64),e.getRequestHeaders().getFirst("X-FocusLedger-Machine-ID")); received.incrementAndGet(); json(e,200,"{\"acknowledged_ids\":[\"stable-event\"]}");
            } catch (Exception ex) { throw new java.io.IOException(ex); }
        });
        JSONObject body = new JSONObject().put("events",new JSONArray().put(new JSONObject().put("id","stable-event")));
        assertEquals(url(fallback),transport.request(config,"POST","/api/v1/usage/batches",body).endpoint()); assertEquals(1,received.get());
    }
    @Test public void authorizationFailureDoesNotTryAnotherServer() throws Exception {
        AtomicInteger received = new AtomicInteger(); primary.createContext("/x", e -> json(e,401,"{}")); fallback.createContext("/x",e->{received.incrementAndGet();json(e,200,"{}");});
        try { transport.request(config,"GET","/x",null); fail(); } catch (Transport.ApiError e) { assertEquals(401,e.status); }
        assertEquals(0,received.get());
    }
    @Test public void redirectsNeverForwardUploadKey() throws Exception {
        AtomicInteger received = new AtomicInteger(); primary.createContext("/x",e->{e.getResponseHeaders().add("Location",url(fallback)+"/x");e.sendResponseHeaders(302,-1);e.close();}); fallback.createContext("/x",e->{received.incrementAndGet();json(e,200,"{}");});
        try { transport.request(config,"GET","/x",null); fail(); } catch (Transport.ApiError e) { assertEquals(302,e.status); }
        assertEquals(0,received.get());
    }
    @Test public void gzipIsNegotiatedAndRejectedCompressionRetriesPlain() throws Exception {
        AtomicInteger count = new AtomicInteger(); primary.createContext("/x",e->{
            int n = count.incrementAndGet(); String encoding=e.getRequestHeaders().getFirst("Content-Encoding");
            if(n==1) { assertNull(encoding); json(e,200,"{\"upload_encodings\":[\"gzip\"]}"); }
            else if(n==2) { assertEquals("gzip",encoding); try (GZIPInputStream in = new GZIPInputStream(e.getRequestBody())) { assertTrue(in.readAllBytes().length > 256); } json(e,415,"{}"); }
            else { assertNull(encoding); json(e,200,"{}"); }
        });
        JSONObject body=new JSONObject().put("padding","a".repeat(1000)); transport.request(config,"POST","/x",body); transport.request(config,"POST","/x",body); transport.request(config,"POST","/x",body); assertEquals(4,count.get());
    }
    @Test public void malformedSuccessDoesNotAcknowledgeAnything() throws Exception {
        primary.createContext("/x",e->json(e,200,"not-json")); fallback.createContext("/x",e->json(e,200,"not-json"));
        try { transport.request(config,"POST","/x",new JSONObject()); fail(); } catch (java.io.IOException expected) {}
    }
}
