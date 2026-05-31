package com.lab.management;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
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

import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends AppCompatActivity {
    private WebView webView;
    private static final int SERVER_PORT = 1880;
    private static final int POLL_INTERVAL_MS = 300;
    private static final int MAX_WAIT_MS = 30000;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Show loading screen
        android.widget.LinearLayout loadingLayout = new android.widget.LinearLayout(this);
        loadingLayout.setOrientation(android.widget.LinearLayout.VERTICAL);
        loadingLayout.setGravity(android.view.Gravity.CENTER);
        loadingLayout.setBackgroundColor(Color.parseColor("#1C2233"));

        TextView loadingTitle = new TextView(this);
        loadingTitle.setText("\u5B9E\u9A8C\u5BA4\u7EFC\u5408\u7BA1\u7406");
        loadingTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 30);
        loadingTitle.setTextColor(Color.WHITE);
        loadingTitle.setTypeface(null, android.graphics.Typeface.BOLD);
        loadingTitle.setGravity(android.view.Gravity.CENTER);
        loadingLayout.addView(loadingTitle);

        TextView loadingStatus = new TextView(this);
        loadingStatus.setText("\u7CFB\u7EDF\u542F\u52A8\u4E2D\uFF0C\u8BF7\u7A0D\u5019...");
        loadingStatus.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 16);
        loadingStatus.setTextColor(Color.parseColor("#7FA8C0"));
        loadingStatus.setGravity(android.view.Gravity.CENTER);
        android.widget.LinearLayout.LayoutParams subP = new android.widget.LinearLayout.LayoutParams(
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT);
        subP.topMargin = 24;
        loadingStatus.setLayoutParams(subP);
        loadingLayout.addView(loadingStatus);

        setContentView(loadingLayout);

        // Initialize Chaquopy Python runtime
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        // Start embedded FastAPI server in background thread
        new Thread(() -> {
            try {
                Python py = Python.getInstance();
                py.getModule("server_main").callAttr("start_server", SERVER_PORT);
            } catch (Exception e) {
                android.util.Log.e("MainActivity", "Python server error", e);
            }
        }).start();

        // Poll server until ready, then load WebView
        new Thread(() -> {
            long start = System.currentTimeMillis();
            boolean ready = false;
            while (System.currentTimeMillis() - start < MAX_WAIT_MS) {
                try {
                    HttpURLConnection conn = (HttpURLConnection)
                            new URL("http://127.0.0.1:" + SERVER_PORT + "/req").openConnection();
                    conn.setConnectTimeout(500);
                    conn.setReadTimeout(500);
                    conn.setRequestMethod("GET");
                    int code = conn.getResponseCode();
                    conn.disconnect();
                    if (code == 200) {
                        ready = true;
                        break;
                    }
                } catch (Exception ignored) {
                }
                try { Thread.sleep(POLL_INTERVAL_MS); } catch (InterruptedException ignored) { break; }
            }
            final boolean serverReady = ready;
            new Handler(Looper.getMainLooper()).post(() -> {
                if (serverReady) {
                    initWebView();
                } else {
                    android.util.Log.e("MainActivity", "Server failed to start within timeout");
                    initWebView();
                }
            });
        }).start();
    }

    private void initWebView() {
        try {
            webView = new WebView(this);
            webView.setLayerType(View.LAYER_TYPE_HARDWARE, null);
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

            webView.setWebViewClient(new WebViewClient() {
                @Override
                public void onPageFinished(WebView view, String url) {
                    super.onPageFinished(view, url);
                    view.setBackgroundColor(Color.TRANSPARENT);
                }
            });

            webView.setWebChromeClient(new WebChromeClient());

            webView.loadUrl("file:///android_asset/www/index.html");

        } catch (Exception e) {
            android.util.Log.e("MainActivity", "Error initializing WebView", e);
            TextView errorView = new TextView(this);
            errorView.setText("WebView initialization failed: " + e.getMessage());
            errorView.setTextColor(Color.RED);
            errorView.setPadding(20, 20, 20, 20);
            setContentView(errorView);
        }
    }
}