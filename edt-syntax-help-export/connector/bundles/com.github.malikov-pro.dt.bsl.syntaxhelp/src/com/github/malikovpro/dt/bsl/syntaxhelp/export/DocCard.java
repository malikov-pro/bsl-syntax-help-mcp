package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

public final class DocCard {
    public final String docId;
    public final String layer;
    public final String kind;
    public final String fullNameRu;
    public final String bodyText;
    public String objectRu;
    public String objectEn;
    public String memberRu;
    public String memberEn;
    public String fullNameEn;
    public String introducedIn;
    public String availability;
    public String syntax;
    public final List<String> aliases = new ArrayList<>();

    public DocCard(String docId, String layer, String kind, String fullNameRu, String bodyText) {
	this.docId = docId;
	this.layer = layer;
	this.kind = kind;
	this.fullNameRu = fullNameRu;
	this.bodyText = bodyText;
    }

    public JsonObject toJson() {
	var json = new JsonObject();
	json.addProperty("doc_id", docId);
	json.addProperty("layer", layer);
	json.addProperty("kind", kind);
	json.addProperty("full_name_ru", fullNameRu);
	json.addProperty("body_text", bodyText);
	putOptional(json, "object_ru", objectRu);
	putOptional(json, "object_en", objectEn);
	putOptional(json, "member_ru", memberRu);
	putOptional(json, "member_en", memberEn);
	putOptional(json, "full_name_en", fullNameEn);
	putOptional(json, "introduced_in", introducedIn);
	putOptional(json, "availability", availability);
	putOptional(json, "syntax", syntax);
	if (!aliases.isEmpty()) {
	    var array = new JsonArray();
	    var seen = new LinkedHashSet<String>();
	    for (var alias : aliases) {
		if (alias != null) {
		    var trimmed = alias.trim();
		    if (!trimmed.isEmpty() && seen.add(trimmed)) {
			array.add(trimmed);
		    }
		}
	    }
	    if (array.size() > 0) {
		json.add("aliases", array);
	    }
	}
	return json;
    }

    private static void putOptional(JsonObject json, String key, String value) {
	if (value != null && !value.isBlank()) {
	    json.addProperty(key, value);
	}
    }
}
