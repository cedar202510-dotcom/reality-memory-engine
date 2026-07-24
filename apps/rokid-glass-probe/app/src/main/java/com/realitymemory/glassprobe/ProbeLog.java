package com.realitymemory.glassprobe;

import android.content.Context;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

public final class ProbeLog {
    private static final String LOG_FILE = "probe-log.jsonl";

    private ProbeLog() {
    }

    public static synchronized void append(Context context, String event, String detail) {
        try {
            JSONObject row = new JSONObject();
            row.put("ts_ms", System.currentTimeMillis());
            row.put("event", event);
            row.put("detail", detail);

            File file = new File(context.getFilesDir(), LOG_FILE);
            FileWriter writer = new FileWriter(file, true);
            writer.write(row.toString());
            writer.write("\n");
            writer.close();
        } catch (Exception ignored) {
            // Logging must never crash the probe app.
        }
    }

    public static synchronized List<String> lastLines(Context context, int maxLines) {
        ArrayDeque<String> lines = new ArrayDeque<>();
        File file = new File(context.getFilesDir(), LOG_FILE);
        if (!file.exists()) {
            return new ArrayList<>();
        }

        try {
            BufferedReader reader = new BufferedReader(new FileReader(file));
            String line;
            while ((line = reader.readLine()) != null) {
                lines.addLast(line);
                while (lines.size() > maxLines) {
                    lines.removeFirst();
                }
            }
            reader.close();
        } catch (Exception ignored) {
        }
        return new ArrayList<>(lines);
    }

    public static File logFile(Context context) {
        return new File(context.getFilesDir(), LOG_FILE);
    }
}
