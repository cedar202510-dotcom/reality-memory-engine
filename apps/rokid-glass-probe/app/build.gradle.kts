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
