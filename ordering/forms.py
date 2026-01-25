# ordering/forms.py
from django import forms
from .models import Product, Category  # 記得引入 Category


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "category",
            "name",
            "price",
            "stock",
            "flavor_options",
            "is_active",
            "description",
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 2,
                    "class": "form-control",
                    "placeholder": "口味說明等...",
                }
            ),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "price": forms.NumberInput(attrs={"class": "form-control"}),
            "stock": forms.NumberInput(attrs={"class": "form-control"}),
            "flavor_options": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "選填，用逗號隔開"}
            ),
            "category": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(
                attrs={"class": "form-check-input", "role": "switch"}
            ),
        }
        labels = {
            "is_active": "立即上架",
            "flavor_options": "口味選項 (選填)",
        }

    # 🔥 新增這段 __init__ 方法
    def __init__(self, *args, **kwargs):
        # 1. 嘗試從參數中取出 'store' (由 View 傳進來)
        store = kwargs.pop("store", None)

        super(ProductForm, self).__init__(*args, **kwargs)

        # 2. 自定義顯示格式： "分類名稱 (分店名稱)"
        self.fields["category"].label_from_instance = (
            lambda obj: f"{obj.name} ({obj.store.name})"
        )

        # 3. (選用) 如果有傳入分店，就只顯示該分店的分類，避免選錯
        if store:
            self.fields["category"].queryset = Category.objects.filter(
                store=store
            ).order_by("sort_order")
