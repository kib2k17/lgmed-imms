package ph.gov.dilg.lgmedimms;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.text.InputType;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.Toast;

/**
 * The whole app: a full-screen WebView onto the LGMED IMMS server.
 *
 * Nothing of the system lives in the APK. The server address is asked for on
 * first launch and kept, so the same APK moves from the office-network address
 * to a real domain later without a rebuild - change it from the app icon's
 * long-press menu, or from the dialog shown when the server can't be reached.
 */
public class MainActivity extends Activity {

    private static final String PREFS = "settings";
    private static final String KEY_SERVER = "server_url";
    private static final String ACTION_CHANGE_SERVER = "ph.gov.dilg.lgmedimms.CHANGE_SERVER";

    private static final int REQUEST_FILE = 1;
    private static final int REQUEST_STORAGE = 2;

    private WebView webView;
    private ValueCallback<Uri[]> fileCallback;
    private Runnable pendingDownload;
    private AlertDialog dialog;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        // Honour the site's <meta name="viewport"> as phone Chrome does - the
        // WebView ignores it by default, which let the page zoom out to a
        // shrunken desktop-like view instead of the responsive mobile layout.
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(false);
        // The layout is built for the screen; pinch-zoom only knocks it askew.
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        // Lets the website tell the app apart from a phone browser if it ever needs to.
        settings.setUserAgentString(settings.getUserAgentString() + " LGMEDIMMSApp");

        CookieManager.getInstance().setAcceptCookie(true);

        webView.setWebViewClient(new Client());
        webView.setWebChromeClient(new Chrome());
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, length) ->
                download(url, userAgent, contentDisposition, mimeType));

        if (savedInstanceState != null && webView.restoreState(savedInstanceState) != null) {
            return;
        }
        start(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (ACTION_CHANGE_SERVER.equals(intent.getAction())) {
            askForServer();
        }
    }

    private void start(Intent intent) {
        String server = serverUrl();
        if (server == null || ACTION_CHANGE_SERVER.equals(intent.getAction())) {
            askForServer();
        } else {
            webView.loadUrl(server);
        }
    }

    // --- Server address ----------------------------------------------------

    private String serverUrl() {
        return getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, null);
    }

    private void saveServerUrl(String url) {
        SharedPreferences.Editor editor = getSharedPreferences(PREFS, MODE_PRIVATE).edit();
        editor.putString(KEY_SERVER, url);
        editor.apply();
    }

    /** "192.168.1.10:8000/" -> "http://192.168.1.10:8000", or null if it isn't an address. */
    private static String normalise(String typed) {
        String url = typed.trim();
        if (url.isEmpty()) {
            return null;
        }
        if (!url.contains("://")) {
            url = "http://" + url;
        }
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        Uri uri = Uri.parse(url);
        if (!URLUtil.isNetworkUrl(url) || uri.getHost() == null || uri.getHost().isEmpty()) {
            return null;
        }
        return url;
    }

    private void askForServer() {
        dismissDialog();

        String current = serverUrl();
        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setSingleLine(true);
        input.setHint(R.string.server_hint);
        input.setText(current != null ? current : "http://");
        input.setSelection(input.getText().length());

        int pad = Math.round(20 * getResources().getDisplayMetrics().density);
        FrameLayout container = new FrameLayout(this);
        container.setPadding(pad, pad / 2, pad, 0);
        container.addView(input);

        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle(R.string.server_title)
                .setMessage(R.string.server_message)
                .setView(container)
                .setCancelable(current != null)
                .setPositiveButton(R.string.connect, null);
        if (current != null) {
            builder.setNegativeButton(R.string.cancel, null);
        }
        dialog = builder.create();
        dialog.show();

        // Set after show() so an invalid address keeps the dialog open.
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String url = normalise(input.getText().toString());
            if (url == null) {
                input.setError(getString(R.string.server_invalid));
                return;
            }
            saveServerUrl(url);
            dismissDialog();
            webView.clearHistory();
            webView.loadUrl(url);
        });
    }

    private void showOffline(String failingUrl, CharSequence reason) {
        if (dialog != null && dialog.isShowing()) {
            return;
        }
        dialog = new AlertDialog.Builder(this)
                .setTitle(R.string.offline_title)
                .setMessage(getString(R.string.offline_message, failingUrl, reason))
                .setCancelable(false)
                .setPositiveButton(R.string.retry, (d, which) -> webView.loadUrl(failingUrl))
                .setNeutralButton(R.string.change_address, (d, which) -> askForServer())
                .create();
        dialog.show();
    }

    private void dismissDialog() {
        if (dialog != null && dialog.isShowing()) {
            dialog.dismiss();
        }
        dialog = null;
    }

    // --- Page loading ------------------------------------------------------

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri target = request.getUrl();
            String server = serverUrl();
            String serverHost = server != null ? Uri.parse(server).getHost() : null;
            String scheme = target.getScheme();

            boolean web = "http".equals(scheme) || "https".equals(scheme);
            if (web && target.getHost() != null && target.getHost().equals(serverHost)) {
                return false;
            }
            // Other websites, mailto:, tel: and the like open in the phone's own apps.
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, target));
            } catch (ActivityNotFoundException ignored) {
                // Nothing on the phone handles it; stay on the current page.
            }
            return true;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                showOffline(request.getUrl().toString(), error.getDescription());
            }
        }
    }

    // --- File uploads ------------------------------------------------------

    private class Chrome extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                         FileChooserParams params) {
            if (fileCallback != null) {
                fileCallback.onReceiveValue(null);
            }
            fileCallback = callback;

            Intent intent = params.createIntent();
            if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
            }
            try {
                startActivityForResult(intent, REQUEST_FILE);
            } catch (ActivityNotFoundException e) {
                fileCallback = null;
                Toast.makeText(MainActivity.this, R.string.no_file_picker, Toast.LENGTH_LONG).show();
                return false;
            }
            return true;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode != REQUEST_FILE) {
            super.onActivityResult(requestCode, resultCode, data);
            return;
        }
        if (fileCallback == null) {
            return;
        }
        Uri[] picked = null;
        if (resultCode == RESULT_OK && data != null) {
            ClipData clip = data.getClipData();
            if (clip != null) {
                picked = new Uri[clip.getItemCount()];
                for (int i = 0; i < clip.getItemCount(); i++) {
                    picked[i] = clip.getItemAt(i).getUri();
                }
            } else if (data.getData() != null) {
                picked = new Uri[]{data.getData()};
            }
        }
        // null tells the page the picker was cancelled, so the next tap opens it again.
        fileCallback.onReceiveValue(picked);
        fileCallback = null;
    }

    // --- Downloads ---------------------------------------------------------

    private void download(String url, String userAgent, String contentDisposition, String mimeType) {
        if (!URLUtil.isNetworkUrl(url)) {
            // blob: and data: links are built inside the page; the download
            // manager can't fetch them.
            Toast.makeText(this, R.string.download_unsupported, Toast.LENGTH_LONG).show();
            return;
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q
                && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            pendingDownload = () -> download(url, userAgent, contentDisposition, mimeType);
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQUEST_STORAGE);
            return;
        }

        String fileName = URLUtil.guessFileName(url, contentDisposition, mimeType);
        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
        // The download manager is a separate process: hand it the login session,
        // or protected documents come back as the login page.
        String cookies = CookieManager.getInstance().getCookie(url);
        if (cookies != null) {
            request.addRequestHeader("Cookie", cookies);
        }
        request.addRequestHeader("User-Agent", userAgent);
        request.setMimeType(mimeType);
        request.setTitle(fileName);
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);

        DownloadManager manager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
        manager.enqueue(request);
        Toast.makeText(this, getString(R.string.downloading, fileName), Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        if (requestCode != REQUEST_STORAGE) {
            super.onRequestPermissionsResult(requestCode, permissions, grantResults);
            return;
        }
        Runnable next = pendingDownload;
        pendingDownload = null;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            if (next != null) {
                next.run();
            }
        } else {
            Toast.makeText(this, R.string.storage_denied, Toast.LENGTH_LONG).show();
        }
    }

    // --- Lifecycle ---------------------------------------------------------

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        webView.saveState(outState);
    }

    @Override
    protected void onPause() {
        super.onPause();
        // Write the session cookie to disk so closing the app doesn't log the user out.
        CookieManager.getInstance().flush();
    }

    @Override
    protected void onDestroy() {
        dismissDialog();
        webView.destroy();
        super.onDestroy();
    }
}
