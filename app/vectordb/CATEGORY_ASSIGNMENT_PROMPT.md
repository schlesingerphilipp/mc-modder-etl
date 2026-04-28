# Category Assignment Prompt

You are an expert software engineer. Given a list of categories and a batch of commit summaries, assign each summary to the most appropriate category from the list. If a summary does not fit any category, assign it to "Other".

## Instructions
- Read the provided list of categories.
- For each commit summary, select the best matching category.
- If none fit, use "Other".
- Return a table with two columns: summary and assigned_category.

## Example Input
Categories:
- Rendering Improvements
- Bug Fixes
- Feature Additions
- Error Handling

Summaries:
1. Refactored the entity rendering pipeline for better performance.
2. Fixed a bug in the chunk loading logic.
3. Added support for custom block textures.
4. Improved error handling in the network layer.

## Example Output
| summary                                                        | assigned_category      |
|---------------------------------------------------------------|-----------------------|
| Refactored the entity rendering pipeline for better performance.| Rendering Improvements |
| Fixed a bug in the chunk loading logic.                        | Bug Fixes             |
| Added support for custom block textures.                       | Feature Additions     |
| Improved error handling in the network layer.                  | Error Handling        |
