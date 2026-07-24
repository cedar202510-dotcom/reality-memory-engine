plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.realitymemory.glasses"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.realitymemory.glasses"
        minSdk = 31
        targetSdk = 35
        versionCode = 2
        versionName = "0.1.1"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "RUNTIME_VERSION", "\"android-glasses/0.1.1\"")
    }

    buildTypes {
        debug {
            buildConfigField("boolean", "DEBUG_PLAINTEXT_FIXTURE_EXPORT", "true")
        }
        release {
            isMinifyEnabled = false
            buildConfigField("boolean", "DEBUG_PLAINTEXT_FIXTURE_EXPORT", "false")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    testOptions {
        unitTests.all {
            it.useJUnit()
        }
    }
}

dependencies {
    val cameraXVersion = "1.4.2"

    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.camera:camera-camera2:$cameraXVersion")
    implementation("androidx.camera:camera-core:$cameraXVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraXVersion")
    implementation("androidx.camera:camera-video:$cameraXVersion")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")

    testImplementation("junit:junit:4.13.2")
}
