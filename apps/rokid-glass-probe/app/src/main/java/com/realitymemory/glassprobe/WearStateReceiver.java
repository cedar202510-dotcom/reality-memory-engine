package com.realitymemory.glassprobe;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

public class WearStateReceiver extends BroadcastReceiver {
    static final String ACTION_TAKE_STATUS_CHANGED = "com.rokid.sprite.ACTION_TAKE_STATUS_CHANGED";
    static final String ACTION_LEG_STATUS_CHANGED = "com.rokid.sprite.ACTION_LEG_STATUS_CHANGED";
    private static final String EXTRA_TAKE_STATE = "glasses_take_state";

    @Override
    public void onReceive(Context context, Intent intent) {
        String detail = describeIntent(intent);
        ProbeLog.append(context, "WEAR_RECEIVER", detail);

        if (ACTION_TAKE_STATUS_CHANGED.equals(intent.getAction())) {
            String state = intent.getStringExtra(EXTRA_TAKE_STATE);
            if ("1".equals(state)) {
                sendService(context, CaptureForegroundService.ACTION_WEAR_DETECTED);
            } else if ("0".equals(state)) {
                sendService(context, CaptureForegroundService.ACTION_STOP);
            }
        }
    }

    static String describeIntent(Intent intent) {
        StringBuilder builder = new StringBuilder();
        builder.append("action=").append(intent.getAction());
        Bundle extras = intent.getExtras();
        if (extras != null) {
            for (String key : extras.keySet()) {
                Object value = extras.get(key);
                builder.append(", ").append(key).append("=").append(value);
            }
        }
        return builder.toString();
    }

    private void sendService(Context context, String action) {
        Intent serviceIntent = new Intent(context, CaptureForegroundService.class);
        serviceIntent.setAction(action);
        try {
            context.startForegroundService(serviceIntent);
        } catch (Exception e) {
            ProbeLog.append(context, "WEAR_SERVICE_START_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }
}
