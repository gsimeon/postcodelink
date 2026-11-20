import React from "react";
import { PostcodeWorkspace } from "./postcodes/PostcodeWorkspace";

export { PostcodeWorkspace } from "./postcodes/PostcodeWorkspace";
export { VerificationStatusBadge } from "./postcodes/VerificationStatusBadge";
export { AddressResultCard } from "./postcodes/AddressResultCard";
export { ProvenancePanel } from "./postcodes/ProvenancePanel";
export { IntegrationStatusPanel } from "./postcodes/IntegrationStatusPanel";
export { CoverageDashboard } from "./postcodes/CoverageDashboard";
export { AddressCleanser } from "./postcodes/AddressCleanser";
export { PostcodeDirectory } from "./postcodes/PostcodeDirectory";

interface PostcodeLookupTabProps {
  onApplyPostcode?: (postcode: string, details?: any) => void;
  onStartDeliveryWithAddress?: (address: string, postcode: string) => void;
  initialPostcode?: string;
}

export const PostcodeLookupTab: React.FC<PostcodeLookupTabProps> = ({
  onApplyPostcode,
  onStartDeliveryWithAddress,
  initialPostcode,
}) => {
  return (
    <PostcodeWorkspace
      onApplyPostcode={onApplyPostcode}
      onStartDeliveryWithAddress={onStartDeliveryWithAddress}
      initialPostcode={initialPostcode}
    />
  );
};

export default PostcodeLookupTab;
