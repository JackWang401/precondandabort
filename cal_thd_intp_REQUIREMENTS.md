# Requirements

This document consolidates the user-entered requirements for the table interpolation and comparison tool. The requirements are organized from a system engineering perspective: data semantics first, then user workflow, visualization behavior, layout control, persistence, and validation.

## 1. Core Purpose

- The tool shall support editing and comparing calibration-style X/Y tables.
- The tool shall present four comparison rows.
- Each comparison row shall contain two stacked table versions and one shared plot.
- Each stacked table pair shall represent the same logical table name with two different versions.
- The plot shall compare the two table versions in the same comparison row.

## 2. Table And Version Data Model

- Each comparison row shall have one shared table name.
- The shared table name shall be displayed as the plot title.
- The two stacked tables in a comparison row shall use the same shared table name.
- Each individual table version shall have its own editable version-info field.
- The version-info field shall be used for the plot legend, not the shared table name.
- The upper table shall reserve and display its own version-info field.
- The lower table shall reserve and display its own version-info field.
- Each table shall support editable X breakpoints and Y values.
- Each table shall support pasting X/Y data copied from Excel into a breakpoint cell.
- Pasted Excel data may be arranged as two horizontal rows or as two vertical columns.
- Pasted Excel data shall support common formatted numeric text, including percentages, comma group separators, currency symbols, accounting parentheses, and Unicode minus signs.
- Percentage-formatted pasted values shall be stored as their displayed numeric value without the percent sign.
- The table point count shall adjust automatically to the number of pasted X/Y points.
- The application shall support one editable global input X value for interpolation.
- Each table shall display a calculated output Y result from the global input X value.
- Each table shall support a row-specific point count, rather than requiring a global point-count control.

## 3. Interpolation Behavior

- The tool shall calculate linear interpolation from each table's X/Y data.
- X values entered out of range shall clamp to the nearest endpoint Y value.
- X breakpoints may be entered in any order; the calculation shall sort them numerically.
- Duplicate X breakpoints shall be rejected because interpolation would be ambiguous.
- Incomplete X/Y points shall not be used as valid interpolation points.
- The tool shall provide clear result status when the input X or table data is invalid.

## 4. Plot Content Requirements

- Each comparison row shall include a plot that compares the two stacked table versions.
- The plot shall fill the available empty space in its plot pane as much as practical.
- The plot shall include a title.
- The plot title shall be the shared table name for that comparison row.
- The plot shall include both X and Y axis labels.
- The X and Y axis labels shall be editable per plot.
- The X and Y axis labels shall not overlap axis tick values.
- The plot shall include numeric X and Y tick values.
- The plot shall display both version curves with visually distinct colors.
- The plot shall display interpolation input markers where applicable.
- The plot shall keep vertical and horizontal whitespace tight enough that the chart area remains usable.

## 5. Legend Requirements

- Plot legends shall use the table version-info values.
- Plot legends shall not use the shared table name.
- Plot legends shall be placed inside the plot in the top-right corner.
- Plot legends shall be displayed vertically.
- Plot legend placement shall reserve enough space to avoid colliding with the primary plot content where practical.

## 6. Per-Plot Controls

- Plot setting controls shall be located above the plot, not above the stacked tables.
- Plot setting controls shall be plot-specific, not global across all plots.
- Each plot shall have its own editable width control.
- Each plot shall have its own editable height control.
- Each plot shall have its own editable X label control.
- Each plot shall have its own editable Y label control.
- Each plot shall have its own editable X minimum range control.
- Each plot shall have its own editable X maximum range control.
- Each plot shall have its own editable Y minimum range control.
- Each plot shall have its own editable Y maximum range control.
- Empty plot range controls shall mean automatic range calculation.
- Manual plot range controls shall apply only when both min and max are valid numeric values and min is less than max.
- Invalid manual range input shall not break plotting; the plot shall fall back to automatic scaling for that axis.

## 7. Layout And Resizing

- Each comparison row shall allow the user to adjust the border between the stacked table pane and the plot pane.
- The table/plot border adjustment shall be row-specific.
- Adjusting the border in one comparison row shall not change the border position in other comparison rows.
- Plot width and height controls shall visibly affect the corresponding plot.
- Plot layout shall avoid excessive top and bottom margins.
- Plot layout shall preserve readable labels, tick values, legends, and title after resizing.
- The application shall keep controls visually close to the content they affect to avoid misleading users.

## 8. Global Controls

- The application shall provide an All X input that applies one X value to every table and version as it is edited.
- The All X input shall be placed with table-oriented controls on the left side of the page, not with plot settings.
- The application shall not provide an Apply X button.
- The application shall not provide Sample buttons.
- The application shall not provide a global Set All Points control.
- The application shall not provide an Undo Points button.
- Buttons whose behavior can discard or overwrite user-entered data shall be avoided or clearly scoped.

## 9. Persistence And Restore

- The application shall persist user input locally in the browser.
- Persisted data shall include shared table names.
- Persisted data shall include per-table version info.
- Persisted data shall include enabled states.
- Persisted data shall include point counts.
- Persisted data shall include X/Y breakpoint values.
- Persisted data shall include the global input X value.
- Persisted data shall include row-specific table/plot split positions.
- Persisted data shall include per-plot width and height settings.
- Persisted data shall include per-plot axis labels.
- Persisted data shall include per-plot manual X/Y range settings.
- Existing saved data shall be migrated without losing user-entered table content.

## 10. Usability And Safety

- Controls shall be scoped so users can predict exactly which table or plot will change.
- Destructive or broad-scope actions shall be minimized.
- Input fields shall not unexpectedly clear existing user data.
- The UI shall avoid misleading control placement.
- The UI shall remain readable and usable after changing plot size, labels, ranges, or split position.
- The application shall tolerate partially entered numeric fields during editing.

## 11. Verification Expectations

- Core interpolation behavior shall be covered by tests.
- State migration behavior shall be covered by tests when saved-state structure changes.
- Per-plot setting persistence shall be verified when adding new plot-specific controls.
- Changes that affect plotting shall be checked for label overlap, legend placement, and usable chart area.
- Changes that affect layout shall be checked across multiple comparison rows to confirm row-specific behavior.
