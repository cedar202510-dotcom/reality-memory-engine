package com.realitymemory.glassprobe.collector;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.ImageFormat;
import android.graphics.Matrix;
import android.graphics.Rect;
import android.graphics.YuvImage;

import androidx.annotation.NonNull;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;

/**
 * CameraX ImageAnalysis 回调：YUV_420_888 → NV21 → JPEG，推给 PreviewStreamServer。
 *
 * 没有观看者时直接丢帧，不做编码，避免白白耗电发热。
 * 帧率由 maxFps 限制（MJPEG 是逐帧全量 JPEG，10fps 已足够调试观感）。
 */
public final class PreviewFrameAnalyzer implements ImageAnalysis.Analyzer {
    private final PreviewStreamServer server;
    private final int jpegQuality;
    private final long minFrameIntervalMs;
    private long lastFrameMs;

    public PreviewFrameAnalyzer(PreviewStreamServer server, int maxFps, int jpegQuality) {
        this.server = server;
        this.jpegQuality = jpegQuality;
        this.minFrameIntervalMs = 1000L / Math.max(1, maxFps);
    }

    @Override
    public void analyze(@NonNull ImageProxy image) {
        try (ImageProxy proxy = image) {
            long now = System.currentTimeMillis();
            if (!server.hasViewers() || now - lastFrameMs < minFrameIntervalMs) {
                return;
            }
            lastFrameMs = now;
            byte[] nv21 = toNv21(proxy);
            YuvImage yuv = new YuvImage(nv21, ImageFormat.NV21, proxy.getWidth(), proxy.getHeight(), null);
            ByteArrayOutputStream jpeg = new ByteArrayOutputStream();
            yuv.compressToJpeg(new Rect(0, 0, proxy.getWidth(), proxy.getHeight()), jpegQuality, jpeg);
            server.submitFrame(rotateIfNeeded(jpeg.toByteArray(), proxy.getImageInfo().getRotationDegrees()));
        } catch (Exception ignored) {
            // 预览是旁路能力，单帧转换失败直接丢帧。
        }
    }

    /** 按 CameraX 报告的 rotationDegrees 转正画面（Rokid 传感器横置，直出是躺倒的）。
     *  预览分辨率下逐帧 decode/rotate/encode 开销可忽略；rotation=0 时零开销直通。 */
    private byte[] rotateIfNeeded(byte[] jpegBytes, int rotationDegrees) {
        if (rotationDegrees == 0) {
            return jpegBytes;
        }
        Bitmap source = BitmapFactory.decodeByteArray(jpegBytes, 0, jpegBytes.length);
        if (source == null) {
            return jpegBytes;
        }
        Matrix matrix = new Matrix();
        matrix.postRotate(rotationDegrees);
        Bitmap rotated = Bitmap.createBitmap(source, 0, 0, source.getWidth(), source.getHeight(), matrix, true);
        source.recycle();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        rotated.compress(Bitmap.CompressFormat.JPEG, jpegQuality, out);
        rotated.recycle();
        return out.toByteArray();
    }

    /** YUV_420_888 三平面（含 row/pixel stride）拷成 NV21（Y 后跟交错的 VU）。 */
    private static byte[] toNv21(ImageProxy image) {
        int width = image.getWidth();
        int height = image.getHeight();
        byte[] nv21 = new byte[width * height * 3 / 2];

        ImageProxy.PlaneProxy yPlane = image.getPlanes()[0];
        ImageProxy.PlaneProxy uPlane = image.getPlanes()[1];
        ImageProxy.PlaneProxy vPlane = image.getPlanes()[2];

        // Y
        ByteBuffer yBuf = yPlane.getBuffer();
        int pos = 0;
        for (int row = 0; row < height; row++) {
            yBuf.position(row * yPlane.getRowStride());
            yBuf.get(nv21, pos, width);
            pos += width;
        }

        // VU 交错（NV21 = ...VUVU）
        int chromaHeight = height / 2;
        int chromaWidth = width / 2;
        ByteBuffer uBuf = uPlane.getBuffer();
        ByteBuffer vBuf = vPlane.getBuffer();
        for (int row = 0; row < chromaHeight; row++) {
            for (int col = 0; col < chromaWidth; col++) {
                int uIndex = row * uPlane.getRowStride() + col * uPlane.getPixelStride();
                int vIndex = row * vPlane.getRowStride() + col * vPlane.getPixelStride();
                nv21[pos++] = vBuf.get(vIndex);
                nv21[pos++] = uBuf.get(uIndex);
            }
        }
        return nv21;
    }
}
