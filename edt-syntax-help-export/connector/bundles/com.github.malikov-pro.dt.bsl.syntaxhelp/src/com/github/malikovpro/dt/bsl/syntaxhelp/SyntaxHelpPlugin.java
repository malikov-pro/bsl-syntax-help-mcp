package com.github.malikovpro.dt.bsl.syntaxhelp;

import org.eclipse.core.runtime.IStatus;
import org.eclipse.core.runtime.Status;
import org.eclipse.core.runtime.preferences.InstanceScope;
import org.eclipse.ui.plugin.AbstractUIPlugin;
import org.eclipse.ui.preferences.ScopedPreferenceStore;
import org.osgi.framework.BundleContext;

public class SyntaxHelpPlugin extends AbstractUIPlugin {
    public static final String PLUGIN_ID = "com.github.malikov-pro.dt.bsl.syntaxhelp";

    private static SyntaxHelpPlugin plugin;
    private ScopedPreferenceStore preferenceStore;

    public static SyntaxHelpPlugin getDefault() {
	return plugin;
    }

    public ScopedPreferenceStore getPreferenceStore() {
	return preferenceStore;
    }

    public static void log(IStatus status) {
	var instance = plugin;
	if (instance == null) {
	    return;
	}
	var log = instance.getLog();
	if (log != null) {
	    log.log(status);
	}
    }

    public static void logError(String message, Throwable throwable) {
	log(new Status(IStatus.ERROR, PLUGIN_ID, message, throwable));
    }

    public static void logWarning(String message) {
	log(new Status(IStatus.WARNING, PLUGIN_ID, message));
    }

    public static void logInfo(String message) {
	log(new Status(IStatus.INFO, PLUGIN_ID, message));
    }

    @Override
    public void start(BundleContext context) throws Exception {
	super.start(context);
	plugin = this;
	preferenceStore = new ScopedPreferenceStore(InstanceScope.INSTANCE, PLUGIN_ID);
    }

    @Override
    public void stop(BundleContext context) throws Exception {
	plugin = null;
	super.stop(context);
    }
}
