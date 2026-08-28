package com.github.malikovpro.dt.bsl.syntaxhelp.ui;

import org.eclipse.core.runtime.preferences.AbstractPreferenceInitializer;
import org.eclipse.core.runtime.preferences.DefaultScope;

import com.github.malikovpro.dt.bsl.syntaxhelp.SyntaxHelpPlugin;
import com.github.malikovpro.dt.bsl.syntaxhelp.export.Layers;

public class SyntaxHelpPreferenceInitializer extends AbstractPreferenceInitializer {

    @Override
    public void initializeDefaultPreferences() {
	var node = DefaultScope.INSTANCE.getNode(SyntaxHelpPlugin.PLUGIN_ID);
	node.put(SyntaxHelpPreferencePage.MCP_URL, SyntaxHelpPreferencePage.DEFAULT_MCP_URL);
	node.put(SyntaxHelpPreferencePage.INGEST_TOKEN, "");
	for (var layer : Layers.ALL) {
	    node.putBoolean(SyntaxHelpPreferencePage.layerKey(layer), Layers.BASE.equals(layer));
	}
    }
}
