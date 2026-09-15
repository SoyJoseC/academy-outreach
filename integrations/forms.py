from django import forms


class CandidateCSVUploadForm(forms.Form):
    csv_file = forms.FileField(
        label="Candidates CSV",
        help_text=(
            "UTF-8 CSV with first_name, last_name, phone, email, country, "
            "and course_interest columns. Maximum size: 5 MB."
        ),
    )

    def clean_csv_file(self):
        uploaded = self.cleaned_data["csv_file"]
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError("CSV file must not exceed 5 MB.")
        if not uploaded.name.lower().endswith(".csv"):
            raise forms.ValidationError("Select a .csv file.")
        return uploaded
