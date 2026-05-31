package com.lab.management;

import android.app.Application;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import androidx.core.content.FileProvider;

import java.io.File;

public class UpdateHelper {
    private static Application sApp;

    public static void init(Application app) {
        sApp = app;
    }

    public static String getUpdateDir() {
        if (sApp == null) return "/tmp";
        File dir = new File(sApp.getCacheDir(), "updates");
        if (!dir.exists()) dir.mkdirs();
        return dir.getAbsolutePath();
    }

    public static boolean installApk(String filePath) {
        if (sApp == null) {
            android.util.Log.e("UpdateHelper", "App context not initialized");
            return false;
        }
        try {
            File file = new File(filePath);
            if (!file.exists()) {
                android.util.Log.e("UpdateHelper", "APK file not found: " + filePath);
                return false;
            }

            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

            Uri uri;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                uri = FileProvider.getUriForFile(sApp,
                        sApp.getPackageName() + ".fileprovider", file);
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } else {
                uri = Uri.fromFile(file);
            }

            intent.setDataAndType(uri, "application/vnd.android.package-archive");
            sApp.startActivity(intent);
            android.util.Log.i("UpdateHelper", "Install intent launched for: " + filePath);
            return true;
        } catch (Exception e) {
            android.util.Log.e("UpdateHelper", "Install APK error", e);
            return false;
        }
    }

    public static boolean uninstallSelf() {
        if (sApp == null) {
            android.util.Log.e("UpdateHelper", "App context not initialized");
            return false;
        }
        try {
            Intent intent = new Intent(Intent.ACTION_DELETE);
            intent.setData(Uri.parse("package:" + sApp.getPackageName()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            sApp.startActivity(intent);
            android.util.Log.i("UpdateHelper", "Uninstall intent launched");
            return true;
        } catch (Exception e) {
            android.util.Log.e("UpdateHelper", "Uninstall error", e);
            return false;
        }
    }
}
