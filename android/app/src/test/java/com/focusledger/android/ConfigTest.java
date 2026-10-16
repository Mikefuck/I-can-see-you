package com.focusledger.android;

import org.junit.Test;
import static org.junit.Assert.*;

public class ConfigTest {
    @Test public void normalizesAddressesWithoutChangingOrigin() {
        assertEquals("https://example.com", Config.normalizeUrl("HTTPS://EXAMPLE.COM:443/"));
        assertEquals("http://192.168.1.1:8080", Config.normalizeUrl("http://192.168.1.1:8080/"));
        assertEquals("http://[::1]:8080", Config.normalizeUrl("http://[::1]:8080"));
    }
    @Test public void refusesCredentialsPathsFragmentsAndInvalidPorts() {
        for (String url : new String[]{"example.com", "https://u:p@example.com", "https://example.com/api", "https://example.com/?x=1", "https://example.com/#a", "http://localhost:0", "http://localhost:99999", "file:///tmp/a"}) {
            try { Config.normalizeUrl(url); fail(url); } catch (IllegalArgumentException expected) {}
        }
    }
    @Test public void serverAndAccountScopesCannotCollide() {
        assertNotEquals(Config.sha256("https://one|1"), Config.sha256("https://two|1"));
        assertNotEquals(Config.sha256("https://one|1"), Config.sha256("https://one|2"));
        assertEquals(64,Config.sha256("x").length());
    }
}
