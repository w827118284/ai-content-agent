from urllib.parse import quote


class MockImageService:
    async def generate_image(self, visual_point: str) -> str:
        return f"https://example.com/mock/image.png?point={quote(visual_point)}"

    async def generate_images(self, visual_points: list[str]) -> list[str]:
        return [
            f"https://example.com/mock/image-{index}.png?point={quote(point)}"
            for index, point in enumerate(visual_points, start=1)
        ]
