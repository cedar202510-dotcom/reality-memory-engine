package com.rokid.os.sprite.record.service;

interface IRecordingCallback {
    void onStarted(int type, String path);
    void onCompleted(int type, String path, boolean success, String message);
    void onError(int type, int errorCode, String message);
}
