package com.github.malikovpro.dt.bsl.syntaxhelp.ui;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;

import org.eclipse.core.runtime.IStatus;
import org.eclipse.core.runtime.jobs.IJobChangeEvent;
import org.eclipse.core.runtime.jobs.Job;
import org.eclipse.core.runtime.jobs.JobChangeAdapter;
import org.eclipse.jface.dialogs.MessageDialog;
import org.eclipse.jface.preference.PreferencePage;
import org.eclipse.swt.SWT;
import org.eclipse.swt.events.SelectionAdapter;
import org.eclipse.swt.events.SelectionEvent;
import org.eclipse.swt.layout.GridData;
import org.eclipse.swt.layout.GridLayout;
import org.eclipse.swt.widgets.Button;
import org.eclipse.swt.widgets.Composite;
import org.eclipse.swt.widgets.Control;
import org.eclipse.swt.widgets.Display;
import org.eclipse.swt.widgets.Group;
import org.eclipse.swt.widgets.Label;
import org.eclipse.swt.widgets.Text;
import org.eclipse.ui.IWorkbench;
import org.eclipse.ui.IWorkbenchPreferencePage;

import com.github.malikovpro.dt.bsl.syntaxhelp.SyntaxHelpPlugin;
import com.github.malikovpro.dt.bsl.syntaxhelp.export.ExportJob;
import com.github.malikovpro.dt.bsl.syntaxhelp.export.IngestClient;
import com.github.malikovpro.dt.bsl.syntaxhelp.export.Layers;

public class SyntaxHelpPreferencePage extends PreferencePage implements IWorkbenchPreferencePage {
    public static final String MCP_URL = "MCP_URL";
    public static final String INGEST_TOKEN = "INGEST_TOKEN";
    public static final String DEFAULT_MCP_URL = "http://127.0.0.1:8004";

    private Text urlText;
    private Text tokenText;
    private Text statusText;
    private final Map<String, Button> layerButtons = new LinkedHashMap<>();
    private Job runningJob;

    public SyntaxHelpPreferencePage() {
	setPreferenceStore(SyntaxHelpPlugin.getDefault().getPreferenceStore());
	setDescription("Выгрузка синтакс-помощника платформы в Docker MCP по HTTP. SQLite в плагине нет.");
    }

    @Override
    public void init(IWorkbench workbench) {
	// none
    }

    public static String layerKey(String layer) {
	return "LAYER_" + layer.replace('.', '_');
    }

    @Override
    protected Control createContents(Composite parent) {
	var root = new Composite(parent, SWT.NONE);
	root.setLayout(new GridLayout(1, false));
	root.setLayoutData(new GridData(SWT.FILL, SWT.FILL, true, true));

	var conn = new Group(root, SWT.NONE);
	conn.setText("MCP");
	conn.setLayout(new GridLayout(2, false));
	conn.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));

	new Label(conn, SWT.NONE).setText("URL контейнера:");
	urlText = new Text(conn, SWT.BORDER);
	urlText.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));

	new Label(conn, SWT.NONE).setText("INGEST_TOKEN:");
	tokenText = new Text(conn, SWT.BORDER | SWT.PASSWORD);
	tokenText.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));

	var layers = new Group(root, SWT.NONE);
	layers.setText("Слои для выгрузки");
	layers.setLayout(new GridLayout(1, false));
	layers.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));
	for (var layer : Layers.ALL) {
	    var button = new Button(layers, SWT.CHECK);
	    button.setText(layer);
	    layerButtons.put(layer, button);
	}

	var buttons = new Composite(root, SWT.NONE);
	buttons.setLayout(new GridLayout(4, false));
	buttons.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));
	createAction(buttons, "Выгрузить", this::startExport);
	createAction(buttons, "Обновить статус", this::startStatus);
	createAction(buttons, "Очистить слои", this::startClearLayers);
	createAction(buttons, "Очистить базу", this::startWipe);

	statusText = new Text(root, SWT.BORDER | SWT.MULTI | SWT.READ_ONLY | SWT.V_SCROLL | SWT.WRAP);
	var statusData = new GridData(SWT.FILL, SWT.FILL, true, true);
	statusData.heightHint = 140;
	statusData.widthHint = 420;
	statusText.setLayoutData(statusData);

	loadValues();
	return root;
    }

    @Override
    public boolean performOk() {
	savePreferences();
	return true;
    }

    @Override
    protected void performApply() {
	savePreferences();
    }

    @Override
    protected void performDefaults() {
	urlText.setText(DEFAULT_MCP_URL);
	tokenText.setText("");
	for (var entry : layerButtons.entrySet()) {
	    entry.getValue().setSelection(Layers.BASE.equals(entry.getKey()));
	}
	super.performDefaults();
    }

    @Override
    public void dispose() {
	if (runningJob != null) {
	    runningJob.cancel();
	}
	super.dispose();
    }

    private void loadValues() {
	var store = getPreferenceStore();
	var url = store.getString(MCP_URL);
	urlText.setText(url == null || url.isBlank() ? DEFAULT_MCP_URL : url);
	tokenText.setText(store.getString(INGEST_TOKEN));
	for (var entry : layerButtons.entrySet()) {
	    entry.getValue().setSelection(store.getBoolean(layerKey(entry.getKey())));
	}
    }

    private void savePreferences() {
	var store = getPreferenceStore();
	var url = urlText.getText().trim();
	store.setValue(MCP_URL, url.isEmpty() ? DEFAULT_MCP_URL : url);
	store.setValue(INGEST_TOKEN, tokenText.getText());
	for (var entry : layerButtons.entrySet()) {
	    store.setValue(layerKey(entry.getKey()), entry.getValue().getSelection());
	}
    }

    private IngestClient client() {
	savePreferences();
	return new IngestClient(urlText.getText().trim(), tokenText.getText());
    }

    private java.util.List<String> selectedLayers() {
	var selected = new ArrayList<String>();
	for (var entry : layerButtons.entrySet()) {
	    if (entry.getValue().getSelection()) {
		selected.add(entry.getKey());
	    }
	}
	return selected;
    }

    private void startExport() {
	var selected = selectedLayers();
	if (selected.isEmpty()) {
	    showStatus("Отметьте хотя бы один слой.");
	    return;
	}
	if (tokenText.getText().isBlank()) {
	    showStatus("Укажите INGEST_TOKEN.");
	    return;
	}
	var job = new ExportJob(selected, client(), this::showStatus);
	runJob(job);
    }

    private void startStatus() {
	var client = client();
	runJob(Job.create("Статус syntax-help MCP", monitor -> {
	    try {
		showStatus(client.formatStatus(client.status()));
	    } catch (Exception e) {
		showStatus(client.describe(e));
	    }
	}));
    }

    private void startClearLayers() {
	var selected = selectedLayers();
	if (selected.isEmpty()) {
	    showStatus("Отметьте слои, которые нужно удалить в MCP.");
	    return;
	}
	if (!MessageDialog.openConfirm(getShell(), "Очистить слои",
		"Удалить в MCP выбранные слои: " + String.join(", ", selected) + "?")) {
	    return;
	}
	var client = client();
	runJob(Job.create("Очистка слоёв syntax-help MCP", monitor -> {
	    try {
		var out = new StringBuilder();
		for (var layer : selected) {
		    out.append(client.deleteLayer(layer)).append('\n');
		}
		showStatus(out.toString().strip());
	    } catch (Exception e) {
		showStatus(client.describe(e));
	    }
	}));
    }

    private void startWipe() {
	if (!MessageDialog.openConfirm(getShell(), "Очистить базу",
		"Удалить всю базу syntax-help MCP? Это нельзя отменить.")) {
	    return;
	}
	var client = client();
	runJob(Job.create("Очистка базы syntax-help MCP", monitor -> {
	    try {
		client.wipeDatabase();
		showStatus("База очищена. Выполните «Выгрузить» — слои соберутся заново.");
	    } catch (Exception e) {
		showStatus(client.describe(e));
	    }
	}));
    }

    private void runJob(Job job) {
	if (runningJob != null && runningJob.getState() != Job.NONE) {
	    showStatus("Дождитесь окончания текущей операции.");
	    return;
	}
	job.setUser(true);
	job.addJobChangeListener(new JobChangeAdapter() {
	    @Override
	    public void done(IJobChangeEvent event) {
		// Страховка: ошибка джобы, не дошедшая через progress, всё равно
		// попадает в поле статуса — молчаливых отказов быть не должно.
		var result = event.getResult();
		if (result != null && (result.getSeverity() & IStatus.ERROR) != 0
			&& result.getMessage() != null && !result.getMessage().isBlank()) {
		    showStatus(result.getMessage());
		}
		if (runningJob == job) {
		    runningJob = null;
		}
	    }
	});
	runningJob = job;
	job.schedule();
    }

    private void showStatus(String text) {
	var display = Display.getDefault();
	if (display == null || display.isDisposed()) {
	    return;
	}
	display.asyncExec(() -> {
	    if (statusText != null && !statusText.isDisposed()) {
		statusText.setText(text == null ? "" : text);
	    }
	});
    }

    private static void createAction(Composite parent, String title, Runnable action) {
	var button = new Button(parent, SWT.PUSH);
	button.setText(title);
	button.addSelectionListener(new SelectionAdapter() {
	    @Override
	    public void widgetSelected(SelectionEvent e) {
		action.run();
	    }
	});
    }
}
