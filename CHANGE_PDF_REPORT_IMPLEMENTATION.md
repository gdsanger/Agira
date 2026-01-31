# Change PDF Report Implementation - Summary

## Feature Overview
This implementation adds a PDF report generation feature for Change objects, allowing users to print ISO-27001 compliant reports directly from the Change detail view.

## Implementation Details

### 1. PDF Report Module (`reports/change_pdf.py`)
- **Function**: `build_change_pdf(change, output)`
- **Format**: A4 (210 x 297 mm)
- **Margins**: 
  - Left/Right: 20mm
  - Top/Bottom: 18mm
- **Components Used** (as required):
  - `SimpleDocTemplate` - PDF document structure
  - `Paragraph` - Text content
  - `Table` - Tabular data (overview, approvals, etc.)
  - `TableStyle` - Table formatting
  - `Spacer` - Vertical spacing

### 2. PDF Sections
The generated PDF includes the following sections:

1. **Header**
   - Document title: "Change Report"
   - Change ID
   - Report generation timestamp

2. **Change Overview** (Key-Value Table)
   - Title
   - Project
   - Status
   - Risk Level
   - Safety Relevant flag
   - Release information
   - Created by / Created at / Updated at

3. **Description & Justification**
   - Change description (multi-line)
   - Risk description (multi-line)

4. **Implementation & Planning**
   - Planned start/end dates
   - Execution date
   - Mitigation plan
   - Rollback plan
   - Communication plan

5. **Approvals & Review**
   - Approver information
   - Approval status
   - Decision timestamps
   - Comments

6. **Organisations**
   - List of assigned organisations

7. **Attachments & References**
   - Placeholder for attachment metadata
   - Note: Binary data not embedded for compliance

### 3. Django Backend

#### View Function (`core/views.py`)
```python
@login_required
def change_print(request, id):
    """Generate and return PDF report for a change."""
```

#### URL Route (`core/urls.py`)
```
GET /changes/<id>/print/
```

#### Response Headers
- `Content-Type: application/pdf`
- `Content-Disposition: inline; filename="change_<id>.pdf"`

### 4. User Interface

#### Button Location
The "Drucken" (Print) button is added to the Change detail page header, alongside existing action buttons (Edit, Delete).

#### Button Appearance
```
[Drucken] [Edit] [Delete]
   ↓
Opens PDF in new browser tab
```

#### Button Styling
- Bootstrap secondary button (`btn btn-secondary`)
- Printer icon (`bi-printer`)
- Opens PDF in new tab (`target="_blank"`)

## ISO 27001 Compliance
- ✅ Complete audit trail with timestamps
- ✅ Approval tracking with decision dates
- ✅ Risk assessment documentation
- ✅ Change history and metadata
- ✅ Read-only PDF format for archival

## Testing Results
All verification checks passed:
- ✅ URL routing correct
- ✅ View function signature correct
- ✅ PDF generation working (produces valid PDF)
- ✅ All Platypus components used
- ✅ Correct page format and margins
- ✅ UI button integrated

## Files Modified
1. `reports/change_pdf.py` - New file (PDF generation module)
2. `core/views.py` - Added `change_print` view function
3. `core/urls.py` - Added URL route for `/changes/<id>/print/`
4. `templates/change_detail.html` - Added "Drucken" button

## Security
- No vulnerabilities detected (CodeQL analysis: 0 alerts)
- User authentication required (`@login_required`)
- No code execution vulnerabilities
- Safe handling of user data

## Usage Example
1. Navigate to any Change detail page: `/changes/<id>/`
2. Click the "Drucken" button in the page header
3. PDF opens in new browser tab/window
4. Can be saved or printed directly from browser

## Future Enhancements (Out of Scope)
- Attachment file embedding
- Custom branding/logo
- Additional export formats (Word, Excel)
- Batch printing multiple changes
