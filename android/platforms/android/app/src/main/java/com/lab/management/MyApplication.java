package com.lab.management;

import android.app.Application;

public class MyApplication extends Application {
    @Override
    public void onCreate() {
        super.onCreate();

        // 初始化OTA更新助手
        UpdateHelper.init(this);
    }
}
