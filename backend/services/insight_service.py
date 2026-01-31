"""Service layer for insight and annotation operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.insight import Insight, InsightAnnotation


class InsightService:
    """Service for managing insights and annotations."""

    async def get_insight_with_annotations(
        self,
        db: AsyncSession,
        insight_id: int,
    ) -> Insight | None:
        """Get insight with all annotations loaded.

        Args:
            db: Database session
            insight_id: ID of the insight to retrieve

        Returns:
            Insight with annotations or None if not found
        """
        query = (
            select(Insight)
            .options(selectinload(Insight.annotations))
            .where(Insight.id == insight_id)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def add_annotation(
        self,
        db: AsyncSession,
        insight_id: int,
        note: str,
    ) -> InsightAnnotation:
        """Add annotation to insight.

        Args:
            db: Database session
            insight_id: ID of the insight to annotate
            note: Annotation text

        Returns:
            Created annotation

        Raises:
            ValueError: If insight not found
        """
        insight = await db.get(Insight, insight_id)
        if not insight:
            raise ValueError(f"Insight with id {insight_id} not found")

        annotation = InsightAnnotation(
            insight_id=insight_id,
            note=note,
        )
        db.add(annotation)
        await db.commit()
        await db.refresh(annotation)
        return annotation

    async def update_annotation(
        self,
        db: AsyncSession,
        annotation_id: int,
        note: str,
    ) -> InsightAnnotation:
        """Update existing annotation.

        Args:
            db: Database session
            annotation_id: ID of the annotation to update
            note: New annotation text

        Returns:
            Updated annotation

        Raises:
            ValueError: If annotation not found
        """
        annotation = await db.get(InsightAnnotation, annotation_id)
        if not annotation:
            raise ValueError(f"Annotation with id {annotation_id} not found")

        annotation.note = note
        await db.commit()
        await db.refresh(annotation)
        return annotation

    async def delete_annotation(
        self,
        db: AsyncSession,
        annotation_id: int,
    ) -> bool:
        """Delete annotation.

        Args:
            db: Database session
            annotation_id: ID of the annotation to delete

        Returns:
            True if deleted, False if not found
        """
        annotation = await db.get(InsightAnnotation, annotation_id)
        if not annotation:
            return False

        await db.delete(annotation)
        await db.commit()
        return True

    async def get_annotation(
        self,
        db: AsyncSession,
        annotation_id: int,
    ) -> InsightAnnotation | None:
        """Get annotation by ID.

        Args:
            db: Database session
            annotation_id: ID of the annotation

        Returns:
            Annotation or None if not found
        """
        return await db.get(InsightAnnotation, annotation_id)


insight_service = InsightService()
