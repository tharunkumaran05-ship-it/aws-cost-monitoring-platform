"""
AWS Cost Optimization Platform

Features:
- Detects unused EBS volumes
- Detects unused Elastic IPs
- Detects EBS snapshots
- Detects idle EC2 instances using CloudWatch metrics
- Retrieves AWS Cost Explorer monthly spend
- Sends optimization reports via Amazon SNS

Author: Tharun Kumaran
"""

import boto3
from datetime import datetime, timedelta, timezone, date

REGION = "ap-southeast-2"

TOPIC_ARN = "arn:aws:sns:ap-southeast-2:<ACCOUNT_ID>:cost-optimization-alerts"

ec2 = boto3.client("ec2", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)
ce = boto3.client("ce", region_name="us-east-1")


def lambda_handler(event, context):

    # =====================================
    # UNUSED EBS VOLUMES
    # =====================================

    volumes = ec2.describe_volumes(
        Filters=[
            {
                "Name": "status",
                "Values": ["available"]
            }
        ]
    )

    unused_volume_count = len(volumes["Volumes"])

    # =====================================
    # UNUSED ELASTIC IPS
    # =====================================

    addresses = ec2.describe_addresses()

    unused_eips = []

    for address in addresses["Addresses"]:
        if "AssociationId" not in address:
            unused_eips.append(address)

    # =====================================
    # SNAPSHOTS
    # =====================================

    snapshots = ec2.describe_snapshots(
        OwnerIds=["self"]
    )

    snapshot_count = len(snapshots["Snapshots"])

    # =====================================
    # EC2 IDLE DETECTION
    # =====================================

    idle_instances = []

    instances = ec2.describe_instances()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=1)

    for reservation in instances["Reservations"]:

        for instance in reservation["Instances"]:

            instance_id = instance["InstanceId"]

            try:

                metrics = cloudwatch.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[
                        {
                            "Name": "InstanceId",
                            "Value": instance_id
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=3600,
                    Statistics=["Average"]
                )

                datapoints = metrics["Datapoints"]

                if len(datapoints) == 0:
                    continue

                avg_cpu = sum(
                    point["Average"]
                    for point in datapoints
                ) / len(datapoints)

                if avg_cpu < 5:
                    idle_instances.append(
                        f"{instance_id} ({avg_cpu:.2f}% CPU)"
                    )

            except Exception:
                pass

    # =====================================
    # COST EXPLORER
    # =====================================

    try:

        today = date.today()

        cost_response = ce.get_cost_and_usage(
            TimePeriod={
                "Start": today.replace(day=1).strftime("%Y-%m-%d"),
                "End": today.strftime("%Y-%m-%d")
            },
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"]
        )

        current_cost = cost_response["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"]

    except Exception:

        current_cost = "0.00"

    # =====================================
    # EMAIL MESSAGE
    # =====================================

    message = f"""
AWS FINOPS COST OPTIMIZATION REPORT

Current AWS Spend: ${current_cost}

Unused EBS Volumes: {unused_volume_count}

Unused Elastic IPs: {len(unused_eips)}

Snapshots Found: {snapshot_count}

Idle EC2 Instances: {len(idle_instances)}

Idle Instances Details:
{chr(10).join(idle_instances) if idle_instances else "None"}

Recommendations:

1. Delete unattached EBS volumes
2. Release unused Elastic IPs
3. Review old snapshots
4. Stop or right-size idle EC2 instances

Generated Automatically by AWS FinOps Platform
"""

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="AWS FinOps Cost Optimization Alert",
        Message=message
    )

    return {
        "statusCode": 200,
        "body": "Cost Optimization Report Sent Successfully"
    }
