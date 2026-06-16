package com.jin.weread.capture;

import android.os.Environment;
import android.webkit.CookieManager;

import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Method;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.net.URLConnection;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.WeakHashMap;

import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

public class WereadCaptureHook implements IXposedHookLoadPackage {
    private static final String TARGET_PACKAGE = "com.tencent.weread";
    private static final String OUTPUT_DIR = "/Android/media/com.tencent.weread/wxread_capture";
    private static final String OUTPUT_FILE = "WXREAD_CURL_BASH.txt";
    private static final Object LOCK = new Object();
    private static final WeakHashMap<Object, RequestState> CONNECTION_STATES = new WeakHashMap<>();
    private static volatile String lastCurl = "";
    private static volatile long lastWriteAt = 0L;
    private static volatile int diagnosticCount = 0;
    private static volatile int requestDiagnosticCount = 0;
    private static volatile Class<?> hookedCookieManagerClass = null;

    @Override
    public void handleLoadPackage(XC_LoadPackage.LoadPackageParam lpparam) {
        if (!TARGET_PACKAGE.equals(lpparam.packageName)) {
            return;
        }
        log("loaded in " + lpparam.packageName);
        hookOkHttp(lpparam.classLoader);
        hookReactNativeNetwork(lpparam.classLoader);
        hookWereadAuth(lpparam.classLoader);
        hookWebView();
        hookHttpURLConnection();
        hookCookieManager();
    }

    private static void hookOkHttp(ClassLoader classLoader) {
        try {
            Class<?> builderClass = XposedHelpers.findClass("okhttp3.Request$Builder", classLoader);
            XposedBridge.hookAllMethods(builderClass, "addHeader", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    inspectOkHttpBuilder(param.thisObject, "okhttp-builder-addHeader");
                }
            });
            XposedBridge.hookAllMethods(builderClass, "header", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    inspectOkHttpBuilder(param.thisObject, "okhttp-builder-header");
                }
            });
            XposedBridge.hookAllMethods(builderClass, "build", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    inspectOkHttpRequest(param.getResult());
                }
            });
            log("hooked okhttp3.Request.Builder.build");
        } catch (Throwable throwable) {
            log("okhttp3 Request.Builder hook unavailable: " + throwable);
        }
        try {
            Class<?> clientClass = XposedHelpers.findClass("okhttp3.OkHttpClient", classLoader);
            Class<?> requestClass = XposedHelpers.findClass("okhttp3.Request", classLoader);
            XposedHelpers.findAndHookMethod(
                    clientClass,
                    "newCall",
                    requestClass,
                    new XC_MethodHook() {
                        @Override
                        protected void beforeHookedMethod(MethodHookParam param) {
                            if (param.args != null && param.args.length > 0) {
                                inspectOkHttpRequest(param.args[0]);
                            }
                        }
                    }
            );
            log("hooked okhttp3.OkHttpClient.newCall");
        } catch (Throwable throwable) {
            log("okhttp3 OkHttpClient hook unavailable: " + throwable);
        }
        try {
            Class<?> chainClass = XposedHelpers.findClass("okhttp3.internal.http.RealInterceptorChain", classLoader);
            Class<?> requestClass = XposedHelpers.findClass("okhttp3.Request", classLoader);
            XposedBridge.hookAllMethods(chainClass, "proceed", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    if (param.args != null && param.args.length > 0 && requestClass.isInstance(param.args[0])) {
                        inspectOkHttpRequest(param.args[0], "okhttp-realchain-proceed");
                    }
                }
            });
            log("hooked okhttp3.internal.http.RealInterceptorChain.proceed");
        } catch (Throwable throwable) {
            log("okhttp3 RealInterceptorChain hook unavailable: " + throwable);
        }
    }

    private static void inspectOkHttpBuilder(Object builder, String source) {
        if (builder == null) {
            return;
        }
        try {
            Object request = XposedHelpers.callMethod(builder, "build");
            inspectOkHttpRequest(request, source);
        } catch (Throwable ignored) {
            // Some intermediate builders are not complete enough to build.
        }
    }

    private static void inspectOkHttpRequest(Object request) {
        inspectOkHttpRequest(request, "okhttp");
    }

    private static void inspectOkHttpRequest(Object request, String source) {
        if (request == null) {
            return;
        }
        try {
            String url = String.valueOf(XposedHelpers.callMethod(request, "url"));
            if (!isWereadUrl(url)) {
                return;
            }
            Map<String, String> headers = new LinkedHashMap<>();
            Object headersObj = XposedHelpers.callMethod(request, "headers");
            Object namesObj = XposedHelpers.callMethod(headersObj, "names");
            if (namesObj instanceof Iterable) {
                for (Object nameObj : (Iterable<?>) namesObj) {
                    String name = String.valueOf(nameObj);
                    String value = String.valueOf(XposedHelpers.callMethod(headersObj, "get", name));
                    headers.put(name, value);
                }
            }
            logRequestDiagnostic(url, headers, source);
            maybeWriteCurl(url, headers, source);
        } catch (Throwable throwable) {
            log("inspect okhttp request failed: " + throwable);
        }
    }

    private static void hookReactNativeNetwork(ClassLoader classLoader) {
        try {
            Class<?> moduleClass = XposedHelpers.findClass(
                    "com.facebook.react.modules.network.NetworkingModule",
                    classLoader
            );
            XposedBridge.hookAllMethods(moduleClass, "sendRequest", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    inspectReactNativeArgs(param.args, "rn-sendRequest");
                }
            });
            XposedBridge.hookAllMethods(moduleClass, "sendRequestInternal", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    inspectReactNativeArgs(param.args, "rn-sendRequestInternal");
                }
            });
            log("hooked React Native NetworkingModule");
        } catch (Throwable throwable) {
            log("React Native network hook unavailable: " + throwable);
        }
        try {
            hookForwardingCookieHandler(classLoader, "g7.ForwardingCookieHandler");
        } catch (Throwable throwable) {
            log("React Native relocated cookie handler hook unavailable: " + throwable);
            try {
                hookForwardingCookieHandler(classLoader, "com.facebook.react.modules.network.ForwardingCookieHandler");
            } catch (Throwable fallbackThrowable) {
                log("React Native cookie handler hook unavailable: " + fallbackThrowable);
            }
        }
    }

    private static void hookForwardingCookieHandler(ClassLoader classLoader, String className) {
        Class<?> handlerClass = XposedHelpers.findClass(className, classLoader);
        XposedHelpers.findAndHookMethod(
                handlerClass,
                "get",
                URI.class,
                Map.class,
                new XC_MethodHook() {
                    @Override
                    protected void afterHookedMethod(MethodHookParam param) {
                        String url = param.args == null || param.args.length == 0
                                ? ""
                                : String.valueOf(param.args[0]);
                        Map<String, String> headers = flattenHeaders(param.getResult());
                        maybeWriteCurl(url, headers, "rn-cookiehandler-get");
                    }
                }
        );
        XposedHelpers.findAndHookMethod(
                handlerClass,
                "put",
                URI.class,
                Map.class,
                new XC_MethodHook() {
                    @Override
                    protected void beforeHookedMethod(MethodHookParam param) {
                        String url = param.args == null || param.args.length == 0
                                ? ""
                                : String.valueOf(param.args[0]);
                        Map<String, String> headers = flattenHeaders(param.args != null && param.args.length > 1 ? param.args[1] : null);
                        maybeWriteCurl(url, headers, "rn-cookiehandler-put");
                    }
                }
        );
        log("hooked React Native ForwardingCookieHandler: " + className);
    }

    private static void hookWereadAuth(ClassLoader classLoader) {
        try {
            Class<?> interceptorClass = XposedHelpers.findClass(
                    "com.tencent.weread.network.interceptor.LoginStateInterceptor",
                    classLoader
            );
            XposedHelpers.findAndHookMethod(
                    interceptorClass,
                    "addLoginStateHeader",
                    Map.class,
                    new XC_MethodHook() {
                        @Override
                        protected void afterHookedMethod(MethodHookParam param) {
                            Map<String, String> headers = flattenHeaders(param.args != null && param.args.length > 0 ? param.args[0] : null);
                            maybeWriteCurl("https://weread.qq.com/web/book/read", headers, "weread-loginstate-header");
                        }
                    }
            );
            log("hooked WeRead LoginStateInterceptor.addLoginStateHeader");
            XposedBridge.hookAllMethods(interceptorClass, "intercept", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    log("LoginStateInterceptor.intercept called");
                }
            });
        } catch (Throwable throwable) {
            log("WeRead LoginStateInterceptor hook unavailable: " + throwable);
        }
        try {
            Class<?> requestInterceptorClass = XposedHelpers.findClass(
                    "com.tencent.weread.network.interceptor.WRRequestInterceptor",
                    classLoader
            );
            XposedBridge.hookAllMethods(requestInterceptorClass, "intercept", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    log("WRRequestInterceptor.intercept called");
                }
            });
            log("hooked WeRead WRRequestInterceptor.intercept");
        } catch (Throwable throwable) {
            log("WeRead WRRequestInterceptor hook unavailable: " + throwable);
        }
    }

    private static void inspectReactNativeArgs(Object[] args, String source) {
        if (args == null) {
            return;
        }
        String url = "";
        Map<String, String> headers = new LinkedHashMap<>();
        for (Object arg : args) {
            if (arg == null) {
                continue;
            }
            String value = String.valueOf(arg);
            if (isWereadUrl(value)) {
                url = value;
            }
            collectReadableHeaders(arg, headers);
        }
        maybeWriteCurl(url, headers, source);
    }

    private static void collectReadableHeaders(Object arg, Map<String, String> headers) {
        try {
            Method sizeMethod = arg.getClass().getMethod("size");
            int size = ((Number) sizeMethod.invoke(arg)).intValue();
            for (int index = 0; index < size; index++) {
                Object row = XposedHelpers.callMethod(arg, "getArray", index);
                if (row == null) {
                    continue;
                }
                String key = String.valueOf(XposedHelpers.callMethod(row, "getString", 0));
                String value = String.valueOf(XposedHelpers.callMethod(row, "getString", 1));
                if (key != null && value != null && !"null".equals(key) && !"null".equals(value)) {
                    headers.put(key, value);
                }
            }
        } catch (Throwable ignored) {
            // Most sendRequest arguments are not ReadableArray header lists.
        }
    }

    private static Map<String, String> flattenHeaders(Object headerMap) {
        Map<String, String> headers = new LinkedHashMap<>();
        if (!(headerMap instanceof Map)) {
            return headers;
        }
        for (Object entryObj : ((Map<?, ?>) headerMap).entrySet()) {
            Map.Entry<?, ?> entry = (Map.Entry<?, ?>) entryObj;
            String key = String.valueOf(entry.getKey());
            Object rawValue = entry.getValue();
            if (rawValue instanceof Iterable) {
                StringBuilder joined = new StringBuilder();
                for (Object item : (Iterable<?>) rawValue) {
                    if (joined.length() > 0) {
                        joined.append("; ");
                    }
                    joined.append(String.valueOf(item));
                }
                headers.put(key, joined.toString());
            } else if (rawValue != null) {
                headers.put(key, String.valueOf(rawValue));
            }
        }
        return headers;
    }

    private static void hookWebView() {
        try {
            XposedHelpers.findAndHookMethod(
                    android.webkit.WebView.class,
                    "loadUrl",
                    String.class,
                    new XC_MethodHook() {
                        @Override
                        protected void beforeHookedMethod(MethodHookParam param) {
                            inspectWebViewUrl(param.args == null || param.args.length == 0 ? "" : String.valueOf(param.args[0]), null);
                        }
                    }
            );
            XposedHelpers.findAndHookMethod(
                    android.webkit.WebView.class,
                    "loadUrl",
                    String.class,
                    Map.class,
                    new XC_MethodHook() {
                        @Override
                        protected void beforeHookedMethod(MethodHookParam param) {
                            String url = param.args == null || param.args.length == 0 ? "" : String.valueOf(param.args[0]);
                            Map<String, String> headers = flattenHeaders(param.args != null && param.args.length > 1 ? param.args[1] : null);
                            inspectWebViewUrl(url, headers);
                        }
                    }
            );
            log("hooked WebView.loadUrl");
        } catch (Throwable throwable) {
            log("WebView hook unavailable: " + throwable);
        }
    }

    private static void inspectWebViewUrl(String url, Map<String, String> headers) {
        if (!isWereadUrl(url)) {
            return;
        }
        Map<String, String> workingHeaders = headers == null ? new LinkedHashMap<String, String>() : new LinkedHashMap<>(headers);
        String cookie = CookieManager.getInstance().getCookie(url);
        if (cookie != null && !cookie.isEmpty()) {
            workingHeaders.put("Cookie", cookie);
        }
        maybeWriteCurl(url, workingHeaders, "webview-loadUrl");
    }

    private static void hookHttpURLConnection() {
        try {
            XposedBridge.hookAllConstructors(URLConnection.class, new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    URLConnection connection = (URLConnection) param.thisObject;
                    RequestState state = stateFor(connection);
                    URL url = connection.getURL();
                    if (url != null) {
                        state.url = url.toString();
                    }
                }
            });
            XposedHelpers.findAndHookMethod(
                    URLConnection.class,
                    "setRequestProperty",
                    String.class,
                    String.class,
                    new XC_MethodHook() {
                        @Override
                        protected void afterHookedMethod(MethodHookParam param) {
                            recordConnectionHeader(param.thisObject, param.args);
                        }
                    }
            );
            XposedHelpers.findAndHookMethod(
                    URLConnection.class,
                    "addRequestProperty",
                    String.class,
                    String.class,
                    new XC_MethodHook() {
                        @Override
                        protected void afterHookedMethod(MethodHookParam param) {
                            recordConnectionHeader(param.thisObject, param.args);
                        }
                    }
            );
            XposedHelpers.findAndHookMethod(URLConnection.class, "getInputStream", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    RequestState state = stateFor(param.thisObject);
                    maybeWriteCurl(state.url, state.headers, "httpurlconnection-input");
                }
            });
            XposedHelpers.findAndHookMethod(HttpURLConnection.class, "getResponseCode", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    RequestState state = stateFor(param.thisObject);
                    maybeWriteCurl(state.url, state.headers, "httpurlconnection-response");
                }
            });
            log("hooked URLConnection");
        } catch (Throwable throwable) {
            log("URLConnection hook unavailable: " + throwable);
        }
    }

    private static void recordConnectionHeader(Object connection, Object[] args) {
        if (!(connection instanceof URLConnection) || args == null || args.length < 2) {
            return;
        }
        RequestState state = stateFor(connection);
        URL url = ((URLConnection) connection).getURL();
        if (url != null) {
            state.url = url.toString();
        }
        if (args[0] != null && args[1] != null) {
            state.headers.put(String.valueOf(args[0]), String.valueOf(args[1]));
        }
        maybeWriteCurl(state.url, state.headers, "httpurlconnection-header");
    }

    private static RequestState stateFor(Object key) {
        synchronized (CONNECTION_STATES) {
            RequestState state = CONNECTION_STATES.get(key);
            if (state == null) {
                state = new RequestState();
                CONNECTION_STATES.put(key, state);
            }
            return state;
        }
    }

    private static void hookCookieManager() {
        try {
            XposedHelpers.findAndHookMethod(
                    CookieManager.class,
                    "getInstance",
                    new XC_MethodHook() {
                        @Override
                        protected void afterHookedMethod(MethodHookParam param) {
                            Object manager = param.getResult();
                            if (manager == null) {
                                return;
                            }
                            hookConcreteCookieManager(manager.getClass());
                        }
                    }
            );
            log("hooked CookieManager.getInstance");
        } catch (Throwable throwable) {
            log("CookieManager hook unavailable: " + throwable);
        }
    }

    private static void hookConcreteCookieManager(Class<?> managerClass) {
        synchronized (LOCK) {
            if (managerClass == hookedCookieManagerClass) {
                return;
            }
            hookedCookieManagerClass = managerClass;
        }
        try {
            XposedHelpers.findAndHookMethod(
                    managerClass,
                    "getCookie",
                    String.class,
                    new XC_MethodHook() {
                        @Override
                        protected void afterHookedMethod(MethodHookParam param) {
                            String url = param.args == null || param.args.length == 0 ? "" : String.valueOf(param.args[0]);
                            String cookie = param.getResult() == null ? "" : String.valueOf(param.getResult());
                            if (!isWereadUrl(url)) {
                                return;
                            }
                            logDiagnostic(url, cookie, "webview-cookie");
                            if (!looksUsefulCookie(cookie)) {
                                return;
                            }
                            Map<String, String> headers = new LinkedHashMap<>();
                            headers.put("Cookie", cookie);
                            maybeWriteCurl(url, headers, "webview-cookie");
                        }
                    }
            );
            log("hooked concrete CookieManager: " + managerClass.getName());
        } catch (Throwable throwable) {
            log("concrete CookieManager hook unavailable: " + managerClass.getName() + ": " + throwable);
        }
        try {
            XposedBridge.hookAllMethods(managerClass, "setCookie", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    if (param.args == null || param.args.length < 2) {
                        return;
                    }
                    String url = String.valueOf(param.args[0]);
                    String cookie = String.valueOf(param.args[1]);
                    if (!isWereadUrl(url)) {
                        return;
                    }
                    Map<String, String> headers = new LinkedHashMap<>();
                    headers.put("Cookie", cookie);
                    maybeWriteCurl(url, headers, "webview-setCookie");
                }
            });
            log("hooked concrete CookieManager.setCookie: " + managerClass.getName());
        } catch (Throwable throwable) {
            log("concrete CookieManager.setCookie hook unavailable: " + managerClass.getName() + ": " + throwable);
        }
    }

    private static void maybeWriteCurl(String url, Map<String, String> headers, String source) {
        if (!isWereadUrl(url) || headers == null || headers.isEmpty()) {
            return;
        }
        String cookie = findHeader(headers, "cookie");
        logDiagnostic(url, cookie, source);
        if (!looksUsefulCookie(cookie) && !looksUsefulMobileAuth(headers)) {
            return;
        }
        String curl = buildCurl(url, headers, cookie);
        long now = System.currentTimeMillis();
        synchronized (LOCK) {
            if (curl.equals(lastCurl) && now - lastWriteAt < 30_000L) {
                return;
            }
            lastCurl = curl;
            lastWriteAt = now;
            writeOutput(curl, source, url);
        }
    }

    private static boolean isWereadUrl(String url) {
        return url != null && url.contains("weread.qq.com");
    }

    private static boolean looksUsefulCookie(String cookie) {
        return cookie != null
                && cookie.contains("wr_")
                && (cookie.contains("wr_skey=") || cookie.contains("wr_vid=") || cookie.contains("wr_rt="));
    }

    private static boolean looksUsefulMobileAuth(Map<String, String> headers) {
        return findHeader(headers, "vid").length() > 0 && findHeader(headers, "accessToken").length() > 0;
    }

    private static void logDiagnostic(String url, String cookie, String source) {
        int count = diagnosticCount;
        if (count >= 30) {
            return;
        }
        diagnosticCount = count + 1;
        log("diagnostic source=" + source
                + " url=" + url
                + " cookieLength=" + (cookie == null ? 0 : cookie.length())
                + " hasWr=" + (cookie != null && cookie.contains("wr_"))
                + " hasWrSkey=" + (cookie != null && cookie.contains("wr_skey=")));
    }

    private static void logRequestDiagnostic(String url, Map<String, String> headers, String source) {
        int count = requestDiagnosticCount;
        if (count >= 80) {
            return;
        }
        requestDiagnosticCount = count + 1;
        log("request source=" + source
                + " url=" + url
                + " headerNames=" + headers.keySet()
                + " hasVid=" + (findHeader(headers, "vid").length() > 0)
                + " hasAccessToken=" + (findHeader(headers, "accessToken").length() > 0)
                + " hasCookie=" + (findHeader(headers, "cookie").length() > 0));
    }

    private static String findHeader(Map<String, String> headers, String target) {
        for (Map.Entry<String, String> entry : headers.entrySet()) {
            if (entry.getKey() != null && entry.getKey().equalsIgnoreCase(target)) {
                return entry.getValue();
            }
        }
        return "";
    }

    private static String buildCurl(String url, Map<String, String> headers, String cookie) {
        List<String> parts = new ArrayList<>();
        parts.add("curl");
        parts.add(shellQuote(normalizeReadUrl(url)));
        for (Map.Entry<String, String> entry : headers.entrySet()) {
            String key = entry.getKey();
            String value = entry.getValue();
            if (key == null || value == null || key.equalsIgnoreCase("cookie")) {
                continue;
            }
            parts.add("-H");
            parts.add(shellQuote(key + ": " + value));
        }
        parts.add("-b");
        parts.add(shellQuote(cookie));
        return join(parts);
    }

    private static String normalizeReadUrl(String url) {
        if (url != null && url.contains("/web/book/read")) {
            int query = url.indexOf('?');
            return query >= 0 ? url.substring(0, query) : url;
        }
        return "https://weread.qq.com/web/book/read";
    }

    private static String shellQuote(String value) {
        if (value == null) {
            return "''";
        }
        return "'" + value.replace("'", "'\"'\"'") + "'";
    }

    private static String join(List<String> parts) {
        StringBuilder builder = new StringBuilder();
        for (int index = 0; index < parts.size(); index++) {
            if (index > 0) {
                builder.append(' ');
            }
            builder.append(parts.get(index));
        }
        return builder.toString();
    }

    private static void writeOutput(String curl, String source, String url) {
        try {
            File base = new File(Environment.getExternalStorageDirectory(), OUTPUT_DIR);
            if (!base.exists() && !base.mkdirs()) {
                log("failed to create output dir: " + base);
                return;
            }
            String timestamp = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date());
            String metadata = "# captured_at=" + timestamp + "\n"
                    + "# source=" + source + "\n"
                    + "# url=" + url + "\n";
            File output = new File(base, OUTPUT_FILE);
            try (FileOutputStream stream = new FileOutputStream(output, false)) {
                stream.write(metadata.getBytes(StandardCharsets.UTF_8));
                stream.write(curl.getBytes(StandardCharsets.UTF_8));
                stream.write('\n');
            }
            log("wrote " + output.getAbsolutePath() + " via " + source);
        } catch (Throwable throwable) {
            log("write output failed: " + throwable);
        }
    }

    private static void log(String message) {
        XposedBridge.log("WeReadCapture: " + message);
    }

    private static final class RequestState {
        String url = "";
        final Map<String, String> headers = new LinkedHashMap<>();
    }
}
