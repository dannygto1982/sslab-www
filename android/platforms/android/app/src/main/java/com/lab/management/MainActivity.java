package com.lab.management;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import android.webkit.WebView;
import android.webkit.WebSettings;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.graphics.Color;
import android.view.View;
import android.widget.TextView;
import androidx.appcompat.app.AppCompatActivity;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import com.chaquo.python.PyObject;

import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends AppCompatActivity {
    private WebView webView;
    private TextView loadingStatus;
    private int actualServerPort = 0;
    private static final int DEFAULT_PORT = 1880;
    private static final int POLL_INTERVAL_MS = 300;
    private static final int MAX_WAIT_MS = 40000;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        android.widget.LinearLayout loadingLayout = new android.widget.LinearLayout(this);
        loadingLayout.setOrientation(android.widget.LinearLayout.VERTICAL);
        loadingLayout.setGravity(android.view.Gravity.CENTER);
        loadingLayout.setBackgroundColor(Color.parseColor("#0D1B2A"));

        TextView loadingTitle = new TextView(this);
        loadingTitle.setText("\u5B9E\u9A8C\u5BA4\u7EFC\u5408\u7BA1\u7406");
        loadingTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 30);
        loadingTitle.setTextColor(Color.WHITE);
        loadingTitle.setTypeface(null, android.graphics.Typeface.BOLD);
        loadingTitle.setGravity(android.view.Gravity.CENTER);
        loadingLayout.addView(loadingTitle);

        loadingStatus = new TextView(this);
        loadingStatus.setText("\u7CFB\u7EDF\u542F\u52A8\u4E2D\uFF0C\u8BF7\u7A0D\u5019...");
        loadingStatus.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 16);
        loadingStatus.setTextColor(Color.parseColor("#60A5FA"));
        loadingStatus.setGravity(android.view.Gravity.CENTER);
        android.widget.LinearLayout.LayoutParams subP = new android.widget.LinearLayout.LayoutParams(
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT);
        subP.topMargin = 24;
        loadingStatus.setLayoutParams(subP);
        loadingLayout.addView(loadingStatus);

        setContentView(loadingLayout);

        // 1) Init Chaquopy Python runtime (~15-30s cold start)
        if (!Python.isStarted()) {
            try {
                Python.start(new AndroidPlatform(this));
            } catch (Exception e) {
                showError("Python\u521D\u59CB\u5316\u5931\u8D25: " + e.getMessage());
                return;
            }
        }

        // 2) Start Python FastAPI server + poll readiness
        new Thread(() -> {
            try {
                Python py = Python.getInstance();
                PyObject result = py.getModule("server_main").callAttr("start_server", DEFAULT_PORT);
                actualServerPort = result.toInt();
                android.util.Log.i("MainActivity", "Server starting on port " + actualServerPort);
            } catch (Exception e) {
                android.util.Log.e("MainActivity", "Server start error", e);
                new Handler(Looper.getMainLooper()).post(() ->
                    showError("\u670D\u52A1\u5668\u542F\u52A8\u5931\u8D25:\n" + e.getMessage()));
                return;
            }

            // 3) Poll until /req responds 200
            long start = System.currentTimeMillis();
            boolean ready = false;
            String pollUrl = "http://127.0.0.1:" + actualServerPort + "/req";

            while (System.currentTimeMillis() - start < MAX_WAIT_MS) {
                try {
                    HttpURLConnection conn = (HttpURLConnection)
                            new URL(pollUrl).openConnection();
                    conn.setConnectTimeout(500);
                    conn.setReadTimeout(500);
                    conn.setRequestMethod("GET");
                    int code = conn.getResponseCode();
                    conn.disconnect();
                    if (code == 200) {
                        ready = true;
                        break;
                    }
                } catch (Exception ignored) {}
                try { Thread.sleep(POLL_INTERVAL_MS); } catch (InterruptedException ignored) { break; }
            }

            final boolean serverReady = ready;
            final int port = actualServerPort;
            new Handler(Looper.getMainLooper()).post(() -> {
                if (serverReady) {
                    initWebView(port);
                } else {
                    showError("\u670D\u52A1\u5668\u542F\u52A8\u8D85\u65F6 ("
                        + (MAX_WAIT_MS / 1000) + "s)\n\u8BF7\u91CD\u542F\u5E94\u7528\u6216\u91CD\u542F\u8BBE\u5907");
                }
            });
        }).start();
    }

    private void showError(String msg) {
        android.util.Log.e("MainActivity", msg);
        loadingStatus.setText(msg);
        loadingStatus.setTextColor(Color.parseColor("#EF4444"));
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        // Kill entire process so no uvicorn thread / port binding survives.
        // Android restarts the process cleanly on next launch.
        Process.killProcess(Process.myPid());
    }

    private void initWebView(int port) {
        try {
            webView = new WebView(this);
            webView.setLayerType(View.LAYER_TYPE_HARDWARE, null);
            webView.setBackgroundColor(Color.parseColor("#0D1B2A"));
            setContentView(webView);

            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.KITKAT) {
                WebView.setWebContentsDebuggingEnabled(true);
            }

            WebSettings settings = webView.getSettings();
            settings.setJavaScriptEnabled(true);
            settings.setDomStorageEnabled(true);
            settings.setDatabaseEnabled(true);
            settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
            settings.setAllowFileAccess(true);
            settings.setAllowFileAccessFromFileURLs(true);
            settings.setAllowUniversalAccessFromFileURLs(true);
            settings.setNeedInitialFocus(false);
            settings.setLoadWithOverviewMode(true);
            settings.setUseWideViewPort(true);
            settings.setRenderPriority(WebSettings.RenderPriority.HIGH);
            webView.setOverScrollMode(View.OVER_SCROLL_NEVER);
            webView.setHorizontalScrollBarEnabled(false);
            webView.setVerticalScrollBarEnabled(false);
            webView.setLongClickable(false);
            webView.setHapticFeedbackEnabled(false);

            webView.setWebViewClient(new WebViewClient() {
                @Override
                public boolean shouldOverrideUrlLoading(WebView view, android.webkit.WebResourceRequest request) {
                    String url = request.getUrl().toString();
                    // 拦截所有导航：在 WebView 内加载，不打开外部浏览器
                    if (url.startsWith("http://127.0.0.1:") || url.startsWith("http://localhost:")) {
                        view.loadUrl(url);
                        return true;
                    }
                    // 阻止 file:// 路径直接跳转，统一走 HTTP
                    if (url.startsWith("file://") && !url.contains("android_asset")) {
                        // 尝试提取路径并跳转到对应 HTTP 路由
                        String path = url.replaceAll(".*/www/", "/");
                        view.loadUrl("http://127.0.0.1:" + port + path);
                        return true;
                    }
                    return false;
                }
            });
            webView.setWebChromeClient(new WebChromeClient());

            // Pass actual server port to frontend via query string
            webView.loadUrl("file:///android_asset/www/index.html?apiPort=" + port);

        } catch (Exception e) {
            showError("WebView\u521D\u59CB\u5316\u5931\u8D25: " + e.getMessage());
        }
    }
}
