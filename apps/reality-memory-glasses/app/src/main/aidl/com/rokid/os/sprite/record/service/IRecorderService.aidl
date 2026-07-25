package com.rokid.os.sprite.record.service;

import android.os.Bundle;
import com.rokid.os.sprite.record.service.IRecordingCallback;

interface IRecorderService {
    boolean startRecording(in Bundle config, IRecordingCallback callback);
    void stopRecording(int type);
    boolean isRecording(int type);
}
