package com.realitymemory.glassprobe.collector;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;

import androidx.core.content.ContextCompat;

import com.realitymemory.glassprobe.ProbeLog;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;

/**
 * 音频采集：官方裸机路线使用标准 AudioRecord。
 *
 * 16 kHz / 单声道 / PCM 16-bit（ASR 常用参数，faster-whisper sidecar 可直接吃）。
 * 每 audio_chunk_seconds 切一段，加 WAV 头后作为 modality=audio 信封入 spool。
 */
public final class AudioCaptureController {
    private static final int SAMPLE_RATE = 16_000;
    private static final int CHANNEL = AudioFormat.CHANNEL_IN_MONO;
    private static final int ENCODING = AudioFormat.ENCODING_PCM_16BIT;

    private final Context context;
    private final CollectorConfig config;
    private final EnvelopeSpooler spooler;
    private final String sessionId;

    private Thread worker;
    private volatile boolean running;

    public AudioCaptureController(Context context, CollectorConfig config, EnvelopeSpooler spooler, String sessionId) {
        this.context = context.getApplicationContext();
        this.config = config;
        this.spooler = spooler;
        this.sessionId = sessionId;
    }

    public synchronized void start() {
        if (running || !config.audioEnabled) {
            return;
        }
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            ProbeLog.append(context, "AUDIO_DENIED", "record audio permission not granted");
            return;
        }
        running = true;
        worker = new Thread(this::recordLoop, "audio-capture");
        worker.start();
        ProbeLog.append(context, "AUDIO_STARTED",
                "rate=" + SAMPLE_RATE + ", chunk_s=" + config.audioChunkSeconds);
    }

    public synchronized void stop() {
        if (!running) {
            return;
        }
        running = false;
        if (worker != null) {
            worker.interrupt();
            worker = null;
        }
        ProbeLog.append(context, "AUDIO_STOPPED", "audio capture stopped");
    }

    private void recordLoop() {
        int minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL, ENCODING);
        AudioRecord recorder = null;
        try {
            recorder = new AudioRecord(
                    MediaRecorder.AudioSource.MIC, SAMPLE_RATE, CHANNEL, ENCODING, minBuffer * 4);
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
                ProbeLog.append(context, "AUDIO_INIT_FAILED", "AudioRecord state=" + recorder.getState());
                return;
            }
            recorder.startRecording();

            byte[] buffer = new byte[minBuffer];
            int chunkBytes = SAMPLE_RATE * 2 * config.audioChunkSeconds; // 16-bit mono
            ByteArrayOutputStream chunk = new ByteArrayOutputStream(chunkBytes);
            long chunkStartMs = System.currentTimeMillis();

            while (running) {
                int read = recorder.read(buffer, 0, buffer.length);
                if (read <= 0) {
                    ProbeLog.append(context, "AUDIO_READ_ERROR", "read=" + read);
                    break;
                }
                chunk.write(buffer, 0, read);
                if (chunk.size() >= chunkBytes) {
                    spoolChunk(chunk.toByteArray(), chunkStartMs);
                    chunk.reset();
                    chunkStartMs = System.currentTimeMillis();
                }
            }
            // 结尾不足一段的音频只要超过 2 秒也入队，避免丢掉最后一句话。
            if (chunk.size() >= SAMPLE_RATE * 2 * 2) {
                spoolChunk(chunk.toByteArray(), chunkStartMs);
            }
        } catch (Exception e) {
            ProbeLog.append(context, "AUDIO_LOOP_ERROR", e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (recorder != null) {
                try {
                    recorder.stop();
                } catch (Exception ignored) {
                }
                recorder.release();
            }
        }
    }

    private void spoolChunk(byte[] pcm, long chunkStartMs) {
        try {
            JSONObject meta = new JSONObject();
            meta.put("sample_rate", SAMPLE_RATE);
            meta.put("channels", 1);
            meta.put("duration_seconds", pcm.length / (double) (SAMPLE_RATE * 2));
            JSONObject envelope = EnvelopeSpooler.buildEnvelope(
                    config, sessionId, "auto", "audio", chunkStartMs, meta);
            spooler.spool(envelope, wrapWav(pcm), "chunk-" + chunkStartMs + ".wav");
            ProbeLog.append(context, "AUDIO_CHUNK_SPOOLED", "bytes=" + pcm.length);
        } catch (Exception e) {
            ProbeLog.append(context, "AUDIO_SPOOL_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    /** PCM16 加标准 44 字节 WAV 头。 */
    private static byte[] wrapWav(byte[] pcm) {
        int byteRate = SAMPLE_RATE * 2;
        int dataLen = pcm.length;
        int totalLen = 36 + dataLen;
        byte[] header = new byte[44];
        writeAscii(header, 0, "RIFF");
        writeIntLE(header, 4, totalLen);
        writeAscii(header, 8, "WAVE");
        writeAscii(header, 12, "fmt ");
        writeIntLE(header, 16, 16);            // fmt chunk size
        writeShortLE(header, 20, (short) 1);   // PCM
        writeShortLE(header, 22, (short) 1);   // mono
        writeIntLE(header, 24, SAMPLE_RATE);
        writeIntLE(header, 28, byteRate);
        writeShortLE(header, 32, (short) 2);   // block align
        writeShortLE(header, 34, (short) 16);  // bits per sample
        writeAscii(header, 36, "data");
        writeIntLE(header, 40, dataLen);

        byte[] wav = new byte[44 + dataLen];
        System.arraycopy(header, 0, wav, 0, 44);
        System.arraycopy(pcm, 0, wav, 44, dataLen);
        return wav;
    }

    private static void writeAscii(byte[] buf, int offset, String text) {
        for (int i = 0; i < text.length(); i++) {
            buf[offset + i] = (byte) text.charAt(i);
        }
    }

    private static void writeIntLE(byte[] buf, int offset, int value) {
        buf[offset] = (byte) (value & 0xff);
        buf[offset + 1] = (byte) ((value >> 8) & 0xff);
        buf[offset + 2] = (byte) ((value >> 16) & 0xff);
        buf[offset + 3] = (byte) ((value >> 24) & 0xff);
    }

    private static void writeShortLE(byte[] buf, int offset, short value) {
        buf[offset] = (byte) (value & 0xff);
        buf[offset + 1] = (byte) ((value >> 8) & 0xff);
    }
}
