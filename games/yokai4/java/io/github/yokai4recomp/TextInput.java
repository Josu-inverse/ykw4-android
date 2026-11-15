package io.github.yokai4recomp;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.text.InputFilter;
import android.view.WindowManager;
import android.widget.EditText;

import java.util.concurrent.CountDownLatch;

/** Text field for the game's software keyboard (the runtime's swkbd applet, svc_am.cpp, calls ask from its own thread). */
public final class TextInput {
    private TextInput() {}

    /** Blocks until the player confirms (the text) or cancels (null). Never call it from the UI thread. */
    public static String ask(final Activity activity, final String initial, final int maxLen) {
        final CountDownLatch done = new CountDownLatch(1);
        final String[] result = {null};
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                final EditText field = new EditText(activity);
                field.setSingleLine(true);
                field.setText(initial == null ? "" : initial);
                if (maxLen > 0) field.setFilters(new InputFilter[] {new InputFilter.LengthFilter(maxLen)});
                AlertDialog dialog = new AlertDialog.Builder(activity)
                        .setTitle("Nombre / Name")
                        .setView(field)
                        .setCancelable(false)
                        .setPositiveButton(android.R.string.ok, new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int which) {
                                result[0] = field.getText().toString();
                            }
                        })
                        .setNegativeButton(android.R.string.cancel, null)
                        .create();
                dialog.setOnDismissListener(new DialogInterface.OnDismissListener() {
                    @Override
                    public void onDismiss(DialogInterface d) {
                        done.countDown();
                    }
                });
                dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE);
                dialog.show();
            }
        });
        try {
            done.await();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return result[0];
    }
}
