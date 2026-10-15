import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Every delivered APK is standalone. The Samsung download omits unrelated
// native libraries; the universal build also supports older phones and emulators.
val deliveryAbi = providers.gradleProperty("flowAbi").orElse("universal").get()
require(deliveryAbi in setOf("universal", "arm64-v8a")) { "flowAbi must be universal or arm64-v8a" }
val preparePreviewAssets by tasks.registering(Sync::class) {
    from("src/main/assets")
    exclude("models/**")
    into(layout.buildDirectory.dir("generated/previewAssets"))
}

android {
    namespace = "com.flowdictation.android"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.flowdictation.android"
        minSdk = 26
        targetSdk = 34
        versionCode = 8
        versionName = "1.5.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            abiFilters += if (deliveryAbi == "arm64-v8a") listOf("arm64-v8a")
                else listOf("arm64-v8a", "armeabi-v7a", "x86_64")
        }
    }

    // Download speech models after installation instead of embedding 120+ MB.
    // Keep the small checksum-pinned VAD and dictionary assets available offline.
    sourceSets.getByName("main").assets.setSrcDirs(listOf(layout.buildDirectory.dir("generated/previewAssets")))

    signingConfigs {
        // Private persistent preview key, supplied only to trusted CI builds.
        // Never commit this key or put it in an Actions cache/artifact.
        val previewKeyPath = System.getenv("FLOW_PREVIEW_KEYSTORE_PATH")
        if (!previewKeyPath.isNullOrBlank()) {
            fun requiredPreviewEnv(name: String): String =
                System.getenv(name)?.takeIf { it.isNotBlank() }
                    ?: throw GradleException("Missing preview signing configuration: $name")
            create("preview") {
                storeFile = file(previewKeyPath)
                storePassword = requiredPreviewEnv("FLOW_PREVIEW_STORE_PASSWORD")
                keyAlias = requiredPreviewEnv("FLOW_PREVIEW_KEY_ALIAS")
                keyPassword = requiredPreviewEnv("FLOW_PREVIEW_KEY_PASSWORD")
            }
        }
        // Optional release key: create android/keystore.properties (see
        // README) to sign release builds; without it, assembleRelease
        // still runs but leaves the APK unsigned.
        val keystorePropsFile = rootProject.file("keystore.properties")
        if (keystorePropsFile.exists()) {
            val keystoreProps = Properties().apply {
                FileInputStream(keystorePropsFile).use(::load)
            }
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            val keystorePropsFile = rootProject.file("keystore.properties")
            if (keystorePropsFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        debug {
            isMinifyEnabled = false
            signingConfigs.findByName("preview")?.let { signingConfig = it }
            // Keep existing Flow data intact when testing a new signing key.
            applicationIdSuffix = ".preview"
            resValue("string", "app_name", "Flow Preview")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    // sherpa-onnx loads .onnx model files via AssetManager; they must not be
    // compressed in the APK or native loading fails.
    androidResources {
        noCompress.add("onnx")
    }
}

// The sherpa-onnx AAR is NOT on Maven Central. It must be downloaded once via
// scripts/fetch-deps.sh into app/libs/ before building.
tasks.named("preBuild") {
    dependsOn(preparePreviewAssets)
    doFirst {
        val aars = file("libs").listFiles { f -> f.extension == "aar" }
        if (aars.isNullOrEmpty()) {
            throw GradleException(
                "Missing sherpa-onnx AAR in app/libs/. Run ./scripts/fetch-deps.sh " +
                    "from the android/ directory first (see android/README.md).",
            )
        }
    }
}

dependencies {
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    // Streaming official .tar.bz2 speech-model imports; pinned Apache release.
    implementation("org.apache.commons:commons-compress:1.28.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar", "*.jar"))))
}
