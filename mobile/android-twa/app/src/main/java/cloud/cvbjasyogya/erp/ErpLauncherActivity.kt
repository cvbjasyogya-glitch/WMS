package cloud.cvbjasyogya.erp

import android.content.Intent
import android.net.Uri
import com.google.androidbrowserhelper.trusted.LauncherActivity

class ErpLauncherActivity : LauncherActivity() {
    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        if (intent != null) {
            setIntent(intent)
        }
    }

    override fun getLaunchingUrl(): Uri {
        return normalizeLaunchUri(intent?.data) ?: Uri.parse(BuildConfig.LAUNCH_URL)
    }

    private fun normalizeLaunchUri(candidate: Uri?): Uri? {
        if (candidate == null) {
            return null
        }

        val webOrigin = Uri.parse(BuildConfig.WEB_ORIGIN)
        if (
            candidate.scheme?.lowercase() != "https" ||
            candidate.host?.lowercase() != webOrigin.host?.lowercase()
        ) {
            return null
        }

        if (!candidate.getQueryParameter("source").isNullOrBlank()) {
            return candidate
        }

        return candidate.buildUpon()
            .appendQueryParameter("source", "android-app")
            .build()
    }
}
