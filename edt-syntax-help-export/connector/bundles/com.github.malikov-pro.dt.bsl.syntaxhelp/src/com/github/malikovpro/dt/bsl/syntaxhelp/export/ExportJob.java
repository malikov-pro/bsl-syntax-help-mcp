package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

import org.eclipse.core.resources.WorkspaceJob;
import org.eclipse.core.runtime.IProgressMonitor;
import org.eclipse.core.runtime.IStatus;
import org.eclipse.core.runtime.Status;
import org.eclipse.core.runtime.SubMonitor;

import com.github.malikovpro.dt.bsl.syntaxhelp.SyntaxHelpPlugin;

public final class ExportJob extends WorkspaceJob {
    public static final int BATCH_SIZE = 200;

    private final List<String> layers;
    private final IngestClient client;
    private final Consumer<String> progress;

    public ExportJob(List<String> layers, IngestClient client, Consumer<String> progress) {
	super("Выгрузка синтакс-помощника в MCP");
	this.layers = List.copyOf(layers);
	this.client = client;
	this.progress = progress == null ? text -> {
	} : progress;
	setUser(true);
    }

    @Override
    public IStatus runInWorkspace(IProgressMonitor monitor) {
	var provider = PlatformDocAccess.getProvider();
	if (provider == null) {
	    return new Status(IStatus.ERROR, SyntaxHelpPlugin.PLUGIN_ID,
		    "PlatformDocProvider недоступен. Откройте BSL-редактор и повторите.");
	}
	var root = SubMonitor.convert(monitor, "Выгрузка слоёв", layers.size() * 100);
	var summary = new StringBuilder();
	try {
	    for (var layer : layers) {
		var layerMonitor = root.split(100);
		exportLayer(provider, layer, layerMonitor, summary);
	    }
	    progress.accept(summary.toString().strip());
	    return Status.OK_STATUS;
	} catch (org.eclipse.core.runtime.OperationCanceledException e) {
	    progress.accept("Выгрузка отменена.");
	    return Status.CANCEL_STATUS;
	} catch (Exception e) {
	    SyntaxHelpPlugin.logError("Ошибка выгрузки синтакс-помощника", e);
	    progress.accept("Ошибка: " + e.getMessage());
	    return new Status(IStatus.ERROR, SyntaxHelpPlugin.PLUGIN_ID, e.getMessage(), e);
	}
    }

    private void exportLayer(com._1c.g5.v8.dt.platform.doc.PlatformDocProvider provider, String layer,
	    SubMonitor monitor, StringBuilder summary) throws Exception {
	monitor.setTaskName("Слой " + layer);
	progress.accept("Слой " + layer + ": чтение дерева…");
	var version = Layers.versionFor(layer);
	var cards = new PlatformDocDumper(provider, version, layer).dump(monitor.split(60));
	if (cards.isEmpty()) {
	    throw new IllegalStateException("Слой " + layer + ": нет страниц для выгрузки");
	}
	progress.accept("Слой " + layer + ": " + cards.size() + " карточек, отправка…");
	var sessionId = client.begin(layer);
	try {
	    var batchMonitor = monitor.split(30);
	    batchMonitor.beginTask("Батчи " + layer, (cards.size() + BATCH_SIZE - 1) / BATCH_SIZE);
	    var accepted = 0;
	    for (var i = 0; i < cards.size(); i += BATCH_SIZE) {
		if (monitor.isCanceled()) {
		    client.abort(sessionId);
		    throw new org.eclipse.core.runtime.OperationCanceledException();
		}
		var slice = cards.subList(i, Math.min(i + BATCH_SIZE, cards.size()));
		var result = client.sendBatch(sessionId, new ArrayList<>(slice));
		accepted = result.has("total") ? result.get("total").getAsInt() : accepted + slice.size();
		batchMonitor.worked(1);
		progress.accept("Слой " + layer + ": отправлено " + accepted + " / " + cards.size());
	    }
	    progress.accept("Слой " + layer + ": commit…");
	    var commit = client.commit(sessionId);
	    sessionId = null;
	    monitor.split(10);
	    var line = "Слой " + layer + ": готово, " + cards.size() + " карточек"
		    + (commit.has("documents") ? ", documents=" + commit.get("documents") : "");
	    summary.append(line).append('\n');
	    progress.accept(line);
	} catch (Exception e) {
	    client.abort(sessionId);
	    throw e;
	}
    }
}
