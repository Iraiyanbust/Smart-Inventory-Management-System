from rest_framework import serializers


class VerifyRowSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)
    date = serializers.DateField(required=False)


class VerifySaveSerializer(serializers.Serializer):
    rows = VerifyRowSerializer(many=True)

    def validate_rows(self, value):
        if not value:
            raise serializers.ValidationError("Provide at least one row to save.")
        if len(value) > 500:
            raise serializers.ValidationError("Too many rows (max 500).")
        return value
