plugins {
    id("com.android.application")
}

android {
    namespace = "com.realitymemory.glassprobe"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.realitymemory.glassprobe"
        minSdk = 31
        targetSdk = 31
        versionCode = 1
        versionName = "0.1.0"
        // 默认禁止明文 HTTP（targetSdk>=28 的系统默认值），release 不放开
        manifestPlaceholders["usesCleartextTraffic"] = "false"
    }

    buildTypes {
        debug {
            // 联调期后端是 http://127.0.0.1:8010（adb reverse）或局域网 IP，都是明文。
            // 不放开的话上传会在 App 内直接抛异常——而 adb shell 里的 curl 不受此限制，
            // 于是「curl 能通、App 传不上去」，这个坑排查起来非常费时间。
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    val cameraXVersion = "1.4.2"

    implementation("androidx.activity:activity:1.9.3")
    implementation("androidx.camera:camera-core:$cameraXVersion")
    implementation("androidx.camera:camera-camera2:$cameraXVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraXVersion")
    implementation("androidx.core:core:1.13.1")
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")
}
