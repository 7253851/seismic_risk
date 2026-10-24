<?xml version='1.0' encoding='utf-8'?>
<qgis minScale="1e+08" hasScaleBasedVisibilityFlag="0" maxScale="0" autoRefreshMode="Disabled" autoRefreshTime="0" version="3.44.15-Solothurn" styleCategories="Symbology|Labeling|Rendering|Legend">
  <pipe-data-defined-properties>
    <Option type="Map">
      <Option value="" type="QString" name="name" />
      <Option name="properties" />
      <Option value="collection" type="QString" name="type" />
    </Option>
  </pipe-data-defined-properties>
  <pipe>
    <provider>
      <resampling zoomedInResamplingMethod="nearestNeighbour" maxOversampling="2" enabled="false" zoomedOutResamplingMethod="nearestNeighbour" />
    </provider>
    <rasterrenderer classificationMin="0" classificationMax="255" opacity="0.8" type="singlebandpseudocolor" nodataColor="" band="1" alphaBand="-1">
      <minMaxOrigin>
        <limits>None</limits>
        <extent>WholeRaster</extent>
        <statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower>
        <cumulativeCutUpper>0.98</cumulativeCutUpper>
        <stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader maximumValue="255" labelPrecision="6" clip="0" minimumValue="0" classificationMode="1" colorRampType="INTERPOLATED">
          <item alpha="255" value="0" color="#808080" label="0" />
          <item alpha="255" value="104" color="#909090" label="104" />
          <item alpha="255" value="160" color="#b7b7b7" label="160" />
          <item alpha="255" value="200" color="#d7d7d7" label="200" />
          <item alpha="255" value="230" color="#efefef" label="230" />
          <item alpha="255" value="245" color="#ffffff" label="245" />
          <item alpha="255" value="255" color="#ffffff" label="255" />
          <rampLegendSettings minimumLabel="" suffix="" direction="0" useContinuousLegend="1" orientation="2" maximumLabel="" prefix="">
            <numericFormat id="basic">
              <Option type="Map">
                <Option type="invalid" name="decimal_separator" />
                <Option value="6" type="int" name="decimals" />
                <Option value="0" type="int" name="rounding_type" />
                <Option value="false" type="bool" name="show_plus" />
                <Option value="true" type="bool" name="show_thousand_separator" />
                <Option value="false" type="bool" name="show_trailing_zeros" />
                <Option type="invalid" name="thousand_separator" />
              </Option>
            </numericFormat>
          </rampLegendSettings>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1" />
    <huesaturation invertColors="0" colorizeStrength="100" colorizeOn="0" colorizeGreen="128" colorizeRed="255" saturation="0" colorizeBlue="128" grayscaleMode="0" />
    <rasterresampler maxOversampling="2" />
    <resamplingStage>resamplingFilter</resamplingStage>
  </pipe>
  <blendMode>0</blendMode>
</qgis>