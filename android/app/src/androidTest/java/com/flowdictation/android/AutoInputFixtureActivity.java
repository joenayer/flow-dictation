package com.flowdictation.android;

import android.app.Activity;
import android.os.Bundle;
import android.text.InputType;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Framework-only external app fixture; its process cannot use the target APK's Kotlin runtime. */
public class AutoInputFixtureActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(24, 48, 24, 24);
        layout.setFocusableInTouchMode(true);
        TextView heading = new TextView(this);
        heading.setText("External app · automatic typing test");
        heading.setTextSize(22f);
        layout.addView(heading);
        addField(layout, "First field", "Hello old world", InputType.TYPE_CLASS_TEXT, null);
        addField(layout, "Second field", "Other field untouched", InputType.TYPE_CLASS_TEXT, null);
        addField(layout, "Empty field", "", InputType.TYPE_CLASS_TEXT, "Type a message");
        addField(layout, "Password field", "private",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD, null);
        Button dismiss = new Button(this);
        dismiss.setText("Dismiss input");
        dismiss.setContentDescription("Dismiss input");
        dismiss.setOnClickListener(view -> {
            InputMethodManager ime = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
            ime.hideSoftInputFromWindow(getWindow().getDecorView().getWindowToken(), 0);
            if (getCurrentFocus() != null) getCurrentFocus().clearFocus();
            layout.requestFocus();
        });
        layout.addView(dismiss);
        setContentView(layout);
        layout.requestFocus();
    }

    private void addField(LinearLayout layout, String label, String initial, int inputType, String hint) {
        EditText field = new EditText(this);
        field.setContentDescription(label);
        field.setSingleLine(true);
        field.setInputType(inputType);
        field.setHint(hint);
        field.setText(initial);
        field.setTextSize(20f);
        field.setMinimumHeight((int) (56 * getResources().getDisplayMetrics().density));
        layout.addView(field, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
    }
}
