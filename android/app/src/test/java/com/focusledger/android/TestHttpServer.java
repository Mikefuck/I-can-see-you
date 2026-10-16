package com.focusledger.android;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Small, loopback-only HTTP fixture; no Android or JDK-specific HTTP server module required. */
final class TestHttpServer {
    interface Handler { void handle(Exchange exchange) throws Exception; }
    static final class Headers extends TreeMap<String,String> {
        Headers() { super(String.CASE_INSENSITIVE_ORDER); }
        String getFirst(String key) { return get(key); }
        void add(String key, String value) { put(key,value); }
    }
    static final class Exchange {
        final Socket socket; final Headers request, response = new Headers(); final byte[] body;
        Exchange(Socket socket, Headers headers, byte[] body) { this.socket=socket;request=headers;this.body=body; }
        Headers getRequestHeaders() { return request; } Headers getResponseHeaders() { return response; }
        InputStream getRequestBody() { return new ByteArrayInputStream(body); }
        OutputStream getResponseBody() throws IOException { return socket.getOutputStream(); }
        void sendResponseHeaders(int status, long size) throws IOException {
            StringBuilder b=new StringBuilder("HTTP/1.1 "+status+" Test\r\nContent-Length: "+Math.max(0,size)+"\r\nConnection: close\r\n");
            response.forEach((k,v)->b.append(k).append(": ").append(v).append("\r\n"));b.append("\r\n");socket.getOutputStream().write(b.toString().getBytes(StandardCharsets.US_ASCII));
        }
        void close() throws IOException { socket.close(); }
    }
    private final ServerSocket server; private final Map<String,Handler> handlers = new ConcurrentHashMap<>();
    private volatile boolean stopped; private volatile Throwable failure;
    private TestHttpServer(InetSocketAddress address) throws IOException { server = new ServerSocket();server.bind(address); }
    static TestHttpServer create(InetSocketAddress address, int backlog) throws IOException { return new TestHttpServer(address); }
    InetSocketAddress getAddress() { return (InetSocketAddress)server.getLocalSocketAddress(); }
    void createContext(String path, Handler handler) { handlers.put(path,handler); }
    void start() {
        Thread thread = new Thread(()->{while(!stopped)try(Socket socket=server.accept()) {
            socket.setSoTimeout(5000); InputStream in=socket.getInputStream(); String first=line(in); if(first==null)continue;
            Headers headers=new Headers();String entry;while((entry=line(in))!=null&&!entry.isEmpty()) {int p=entry.indexOf(':');if(p>0)headers.put(entry.substring(0,p),entry.substring(p+1).trim());}
            int size=Integer.parseInt(headers.getOrDefault("Content-Length","0"));byte[] body=new byte[size];int pos=0,n;
            while(pos<size&&(n=in.read(body,pos,size-pos))>0)pos+=n;
            Handler handler=handlers.get(first.split(" ")[1]);Exchange exchange=new Exchange(socket,headers,body);
            if(handler==null){exchange.sendResponseHeaders(404,0);exchange.close();}else handler.handle(exchange);
        }catch(SocketException e){if(!stopped)failure=e;}catch(Throwable e){failure=e;}});
        thread.setDaemon(true);thread.start();
    }
    void stop(int delay) { stopped=true;try{server.close();}catch(IOException ignored){} if(failure!=null)throw new AssertionError("HTTP fixture failed",failure); }
    private static String line(InputStream in) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream();int ch;while((ch=in.read())!=-1){if(ch=='\n')break;if(ch!='\r')out.write(ch);}
        return ch==-1&&out.size()==0?null:out.toString(StandardCharsets.US_ASCII.name());
    }
}
